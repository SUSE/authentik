from typing import Any

from authentik.core.models import User
from authentik.providers.scim.clients.users import SCIMUserClient as BaseSCIMUserClient
from authentik.providers.scim.models import (
    SCIMProviderUser,
)

SUSE_SCIM_LAST_UPDATED_ATTR = "suse_last_updated"


class SUSESCIMUserClient(BaseSCIMUserClient):
    """SCIM client for users"""

    def update(self, user: User, connection: SCIMProviderUser):
        # TODO In a perfect world we would also store and verify the
        #  hash of the property mapping source code here
        # Workaround for https://github.com/goauthentik/authentik/issues/25832
        if (
            SUSE_SCIM_LAST_UPDATED_ATTR in connection.attributes
            and connection.attributes[SUSE_SCIM_LAST_UPDATED_ATTR] == user.last_updated.isoformat()
        ):
            return

        super().update(user, connection)

        # This would save the connection twice because it was already saved in super :/
        # Store this per user so that we only update the baseline when it was successful
        connection.attributes[SUSE_SCIM_LAST_UPDATED_ATTR] = user.last_updated.isoformat()
        connection.save()

    def diff(self, local_created: dict[str, Any], connection: SCIMProviderUser):
        # Would always return true because of
        # https://github.com/goauthentik/authentik/issues/25832 anyways.
        return True
