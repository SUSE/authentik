"""User client"""

from copy import deepcopy
from itertools import batched
from typing import Any

from django.db import transaction
from django.utils.http import urlencode
from orjson import dumps
from pydantic import ValidationError

from authentik.core.models import User
from authentik.lib.merge import MERGE_LIST_UNIQUE
from authentik.lib.sync.mapper import PropertyMappingManager
from authentik.lib.sync.outgoing.exceptions import ObjectExistsSyncException, StopSync
from authentik.policies.utils import delete_none_values
from authentik.providers.scim.clients.base import SCIMClient
from authentik.providers.scim.clients.schema import (
    SCIM_USER_SCHEMA,
    PatchOp,
    PatchOperation,
    PatchRequest,
)
from authentik.providers.scim.clients.schema import (
    User as SCIMUserSchema,
)
from authentik.providers.scim.models import (SCIMMapping, SCIMProvider, SCIMProviderUser, SCIMCompatibilityMode)


class SCIMUserClient(SCIMClient[User, SCIMProviderUser, SCIMUserSchema]):
    """SCIM client for users"""

    connection_type = SCIMProviderUser
    connection_type_query = "user"
    mapper: PropertyMappingManager

    def __init__(self, provider: SCIMProvider):
        super().__init__(provider)
        self.mapper = PropertyMappingManager(
            self.provider.property_mappings.all().order_by("name").select_subclasses(),
            SCIMMapping,
            ["provider", "connection"],
        )

    def to_schema(self, obj: User, connection: SCIMProviderUser) -> SCIMUserSchema:
        """Convert authentik user into SCIM"""
        raw_scim_user = super().to_schema(obj, connection)
        try:
            scim_user = SCIMUserSchema.model_validate(delete_none_values(raw_scim_user))
        except ValidationError as exc:
            raise StopSync(exc, obj) from exc
        if SCIM_USER_SCHEMA not in scim_user.schemas:
            scim_user.schemas.insert(0, SCIM_USER_SCHEMA)
        # As this might be unset, we need to tell pydantic it's set so ensure the schemas
        # are included, even if its just the defaults
        scim_user.schemas = list(scim_user.schemas)
        if not scim_user.externalId:
            scim_user.externalId = str(obj.uid)
        return scim_user

    def delete(self, identifier: str):
        """Delete user"""
        SCIMProviderUser.objects.filter(provider=self.provider, scim_id=identifier).delete()
        return self._request("DELETE", f"/Users/{identifier}")

    def create(self, user: User):
        """Create user from scratch and create a connection object"""
        scim_user = self.to_schema(user, None)
        with transaction.atomic():
            try:
                response = self._request(
                    "POST",
                    "/Users",
                    json=scim_user.model_dump(
                        mode="json",
                        exclude_unset=True,
                    ),
                )
            except ObjectExistsSyncException as exc:
                if not self._config.filter.supported:
                    raise exc
                users = self._request(
                    "GET",
                    f"/Users?{urlencode({'filter': f'userName eq "{scim_user.userName}"'})}",
                )
                users_res = users.get("Resources", [])
                if len(users_res) < 1:
                    raise exc
                return SCIMProviderUser.objects.create(
                    provider=self.provider,
                    user=user,
                    scim_id=users_res[0]["id"],
                    attributes=users_res[0],
                )
            else:
                scim_id = response.get("id")
                if not scim_id or scim_id == "":
                    raise StopSync("SCIM Response with missing or invalid `id`")
                return SCIMProviderUser.objects.create(
                    provider=self.provider, user=user, scim_id=scim_id, attributes=response
                )

    def diff(self, local_created: dict[str, Any], connection: SCIMProviderUser):
        """Check if a user is different than what we last wrote to the remote system.
        Returns true if there is a difference in data."""
        local_known = connection.attributes
        local_updated = deepcopy(local_known)
        MERGE_LIST_UNIQUE.merge(local_updated, local_created)
        return dumps(local_updated) != dumps(local_known)

    def update(self, user: User, connection: SCIMProviderUser):
        """Update existing user"""
        scim_user = self.to_schema(user, connection)
        scim_user.id = connection.scim_id
        payload = scim_user.model_dump(
            mode="json",
            exclude_unset=True,
        )
        if not self.diff(payload, connection):
            self.logger.debug("Skipping user write as data has not changed")
            return

        if self._config.patch.supported:
            match connection.provider.compatibility_mode:
                case SCIMCompatibilityMode.AWS:
                    self._update_patch_aws(payload, connection)
                case _:
                    self._update_patch(payload, connection)
            response = self._request("GET", f"/Users/{connection.scim_id}")
        else:
            response = self._update_put(payload, connection)

        connection.attributes = response
        connection.save()

    def _update_patch(self, payload, connection):
        """Update existing user using PATCH (replace)"""
        op = PatchOperation(
            op=PatchOp.replace,
            path=None,
            value=payload,
        )
        return self._patch_chunked(connection.scim_id, op)

    def _patch_chunked(
        self,
        group_id: str,
        *ops: PatchOperation,
    ):
        """Helper function that chunks patch requests based on the maxOperations attribute.
        This is not strictly according to specs but there's nothing in the schema that allows the
        us to know what the maximum patch operations per request should be."""
        chunk_size = self._config.bulk.maxOperations
        if chunk_size < 1:
            chunk_size = len(ops)
        if len(ops) < 1:
            return

        for chunk in batched(ops, chunk_size, strict=False):
            req = PatchRequest(Operations=list(chunk))
            self._request(
                "PATCH",
                f"/Users/{group_id}",
                json=req.model_dump(mode="json", exclude_none=True),
            )

    def _update_patch_aws(self, payload, connection):
        # from: https://docs.aws.amazon.com/singlesignon/latest/developerguide/patchuser.html
        supported_fields = (
            "userName", "active", "externalId", "displayName", "nickName",
            "profileUrl", "title", "userType", "preferredLanguage", "locale",
            "timezone", "name", "enterprise", "emails", "addresses",
            "phoneNumbers",
        )

        user_dict = scim_group.model_dump(mode="json", exclude_unset=True)
        patch_ops = []

        for attr in supported_fields:
            op = PatchOp.replace
            if attr not in connection.attributes:
                if attr not in payload:
                    # skip
                    continue

                op = PatchOp.add

            patch_ops.append(
                PatchOperation(
                    op=op,
                    path=attr,
                    value=payload[attr],
                )
            )

        self._patch_chunked(connection.scim_id, *patch_ops)

    def _update_put(self, payload, connection):
        """Update existing user using PUT"""
        return self._request(
            "PUT",
            f"/Users/{connection.scim_id}",
            json=payload,
        )
