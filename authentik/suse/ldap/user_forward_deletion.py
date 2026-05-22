from collections.abc import Generator
from itertools import batched
from uuid import uuid4

from ldap3 import SUBTREE

from authentik.sources.ldap.models import UserLDAPSourceConnection

UPDATE_CHUNK_SIZE = 10_000
DELETE_CHUNK_SIZE = 50


class UserForwardDeletion:
    def get_objects(self, **kwargs) -> Generator:
        if not self._source.sync_users or not self._source.delete_not_found_objects:
            self._task.info("User syncing is disabled for this Source")
            return iter(())

        uuid = uuid4()
        paged_users = self.search_paginator(
            search_base=self.base_dn_users,
            search_filter=self._source.user_object_filter,
            search_scope=SUBTREE,
            attributes=[self._source.object_uniqueness_field],
            chunk_size=UPDATE_CHUNK_SIZE,
            **kwargs,
        )
        for batch in paged_users:
            identifiers = []
            for user in batch:
                if not (attributes := self.get_attributes(user)):
                    continue
                if identifier := self.get_identifier(attributes):
                    identifiers.append(identifier)
            UserLDAPSourceConnection.objects.filter(identifier__in=identifiers).update(
                validated_by=uuid
            )

        return batched(
            UserLDAPSourceConnection.objects.filter(source=self._source)
            .exclude(validated_by=uuid)
            .values_list("user", flat=True)
            .iterator(chunk_size=DELETE_CHUNK_SIZE),
            DELETE_CHUNK_SIZE,
            strict=False,
        )
