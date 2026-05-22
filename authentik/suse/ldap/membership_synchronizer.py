"""Sync LDAP Users and groups into authentik"""

from typing import Any

from django.db.models import Q
from ldap3 import SUBTREE
from ldap3.utils.conv import escape_filter_chars

from authentik.core.models import Group, User
from authentik.sources.ldap.models import LDAP_DISTINGUISHED_NAME, LDAP_UNIQUENESS, LDAPSource
from authentik.tasks.models import Task


class MembershipSynchronizer:
    """Sync LDAP Users and groups into authentik"""

    group_cache: dict[str, Group]

    def __init__(self, source: LDAPSource, task: Task):
        super().__init__(source, task)
        self.group_cache: dict[str, Group] = {}

    @staticmethod
    def name() -> str:
        return "membership"

    def get_iterator(
        self,
        since=None,
        search_scope=SUBTREE,
        search_filter=None,
        search_base=None,
        **kwargs,
    ):
        if not search_base:
            search_base = self.base_dn_groups
        if not search_filter:
            search_filter = self._source.group_object_filter
        if since:
            search_filter = self.add_modify_timestamp_filter(search_filter, since)

        attributes = [self._source.object_uniqueness_field, LDAP_DISTINGUISHED_NAME]
        if not self._source.lookup_groups_from_user:
            attributes.append(self._source.group_membership_field)

        return self.search_generator(
            search_base=search_base,
            search_filter=search_filter,
            search_scope=search_scope,
            attributes=attributes,
            **kwargs,
        )

    def get_objects(self, since=None, **kwargs):
        if not self._source.sync_groups:
            self._task.info("group syncing is disabled for this Source")
            return iter(())

        search_filter = self._source.group_object_filter
        if since:
            search_filter = self.add_modify_timestamp_filter(search_filter, since)

        attributes = [self._source.object_uniqueness_field, LDAP_DISTINGUISHED_NAME]
        if not self._source.lookup_groups_from_user:
            attributes.append(self._source.group_membership_field)

        return self.search_paginator(
            search_base=self.base_dn_groups,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=attributes,
            **kwargs,
        )

    def sync_single_record(self, group_entry):
        if self._source.lookup_groups_from_user:
            group_dn = group_entry.get("dn", {})
            escaped_dn = escape_filter_chars(group_dn)
            group_filter = f"({self._source.group_membership_field}={escaped_dn})"
            members = []

            for group_member in self.search_generator(
                search_base=self.base_dn_users,
                search_filter=group_filter,
                search_scope=SUBTREE,
                attributes=[self._source.object_uniqueness_field],
            ):
                group_member_dn = group_member.get("dn", {})
                members.append(group_member_dn)
        else:
            if (attributes := self.get_attributes(group_entry)) is None:
                return None, 0
            members = attributes.get(self._source.group_membership_field, [])

        ak_group = self.get_group(group_entry)
        if not ak_group:
            return None, 0

        users = User.objects.filter(
            Q(**{f"attributes__{self._source.user_membership_attribute}__in": members})
            | Q(
                **{
                    f"attributes__{self._source.user_membership_attribute}__isnull": True,
                    "ak_groups__in": [ak_group],
                }
            )
        ).distinct()

        ak_group.users.set(users)
        ak_group.save()
        return ak_group, users.count()

    def sync(self, page_data: list) -> int:
        """Iterate over all Users and assign Groups using memberOf Field"""
        if not self._source.sync_groups:
            self._task.info("Group syncing is disabled for this Source")
            return -1
        membership_count = 0
        for entry in page_data:
            group, user_count = self.sync_single_record(entry)
            if group:
                membership_count += 1
                membership_count += user_count

        self._logger.debug("Successfully updated group membership")
        return membership_count

    def get_group(self, group_dict: dict[str, Any]) -> Group | None:
        """Check if we fetched the group already, and if not cache it for later"""
        group_dn = group_dict.get("attributes", {}).get(LDAP_DISTINGUISHED_NAME, [])
        group_uniq = group_dict.get("attributes", {}).get(self._source.object_uniqueness_field, [])
        # group_uniq might be a single string or an array with (hopefully) a single string
        if isinstance(group_uniq, list):
            if len(group_uniq) < 1:
                self._task.info(
                    f"Group does not have a uniqueness attribute: '{group_dn}'",
                    group=group_dn,
                )
                return None
            group_uniq = group_uniq[0]
        if group_uniq not in self.group_cache:
            groups = Group.objects.filter(**{f"attributes__{LDAP_UNIQUENESS}": group_uniq})
            if not groups.exists():
                if self._source.sync_groups:
                    self._task.info(
                        f"Group does not exist in our DB yet, run sync_groups first: '{group_dn}'",
                        group=group_dn,
                    )
                return None
            self.group_cache[group_uniq] = groups.first()
        return self.group_cache[group_uniq]
