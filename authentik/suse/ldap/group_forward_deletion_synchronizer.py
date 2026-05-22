"""Sync LDAP Users and groups into authentik"""

from collections.abc import Generator
from itertools import batched
from uuid import uuid4

from ldap3 import SUBTREE

from authentik.sources.ldap.models import GroupLDAPSourceConnection
from authentik.sources.ldap.sync.forward_delete_users import DELETE_CHUNK_SIZE, UPDATE_CHUNK_SIZE


class GroupForwardDeletionSynchronizer:
    def get_objects(self, **kwargs) -> Generator:
        if not self._source.sync_groups or not self._source.delete_not_found_objects:
            self._task.info("Group syncing is disabled for this Source")
            return iter(())

        uuid = uuid4()
        paged_groups = self.search_paginator(
            search_base=self.base_dn_groups,
            search_filter=self._source.group_object_filter,
            search_scope=SUBTREE,
            attributes=[self._source.object_uniqueness_field],
            chunk_size=UPDATE_CHUNK_SIZE,
            **kwargs,
        )
        for batch in paged_groups:
            identifiers = []
            for group in batch:
                if not (attributes := self.get_attributes(group)):
                    continue
                if identifier := self.get_identifier(attributes):
                    identifiers.append(identifier)
            GroupLDAPSourceConnection.objects.filter(identifier__in=identifiers).update(
                validated_by=uuid
            )

        return batched(
            GroupLDAPSourceConnection.objects.filter(source=self._source)
            .exclude(validated_by=uuid)
            .values_list("group", flat=True)
            .iterator(chunk_size=DELETE_CHUNK_SIZE),
            DELETE_CHUNK_SIZE,
            strict=False,
        )
