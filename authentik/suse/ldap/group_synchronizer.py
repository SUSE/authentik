"""Sync LDAP Users and groups into authentik"""

from django.core.exceptions import FieldError
from django.db.utils import IntegrityError
from ldap3 import SUBTREE

from authentik.core.expression.exceptions import (
    PropertyMappingExpressionException,
    SkipObjectException,
)
from authentik.core.models import Group
from authentik.events.models import Event, EventAction
from authentik.lib.sync.outgoing.exceptions import StopSync
from authentik.sources.ldap.models import (
    LDAP_UNIQUENESS,
    GroupLDAPSourceConnection,
    flatten,
)


class GroupSynchronizer:
    def get_filter_and_base(
        self, attribute_name=None, attribute_value=None, search_base=None, dn=None
    ):
        return super().get_filter_and_base(
            search_base=search_base or self.base_dn_groups,
            attribute_name=attribute_name,
            attribute_value=attribute_value,
            dn=dn,
        )

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

        return self.search_generator(
            search_base=search_base,
            search_filter=search_filter,
            search_scope=search_scope,
            attributes=self.get_ldap_attributes(),
            **kwargs,
        )

    def get_objects(self, since=None, **kwargs):
        if not self._source.sync_groups:
            self._task.info("group syncing is disabled for this Source")
            return iter(())

        search_filter = self._source.group_object_filter
        if since:
            search_filter = self.add_modify_timestamp_filter(search_filter, since)

        return self.search_paginator(
            search_base=self.base_dn_groups,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=self.get_ldap_attributes(),
            **kwargs,
        )

    # sync_single_record(self, group : dict) -> none | tuple[group, bool]
    def sync_single_record(self, group):
        """Process a single ldap record into a Group"""
        if (attributes := self.get_attributes(group)) is None:
            return None, None
        group_dn = flatten(flatten(group.get("entryDN", group.get("dn"))))
        if not (uniq := self.get_identifier(attributes)):
            self._task.info(
                f"Uniqueness field not found/not set in attributes: '{group_dn}'",
                attributes=list(attributes.keys()),
                dn=group_dn,
            )
            return None, None
        try:
            defaults = {
                k: flatten(v)
                for k, v in self.mapper.build_object_properties(
                    object_type=Group,
                    manager=self.manager,
                    user=None,
                    request=None,
                    dn=group_dn,
                    ldap=attributes,
                ).items()
            }
            if "name" not in defaults:
                raise IntegrityError("Name was not set by propertymappings")
            # Special check for `users` field, as this is an M2M relation, and cannot be sync'd
            if "users" in defaults:
                del defaults["users"]
            parent = defaults.pop("parent", None)
            ak_group, created = Group.update_or_create_attributes(
                {
                    f"attributes__{LDAP_UNIQUENESS}": uniq,
                },
                defaults,
            )
            if parent:
                ak_group.parents.add(parent)
            self._logger.debug("Created group with attributes", **defaults)
            if not GroupLDAPSourceConnection.objects.filter(source=self._source, identifier=uniq):
                GroupLDAPSourceConnection.objects.create(
                    source=self._source, group=ak_group, identifier=uniq
                )
        except SkipObjectException:
            return None, None
        except PropertyMappingExpressionException as exc:
            raise StopSync(exc, None, exc.mapping) from exc
        except (IntegrityError, FieldError, TypeError, AttributeError) as exc:
            Event.new(
                EventAction.CONFIGURATION_ERROR,
                message=(
                    f"Failed to create group: {str(exc)} "
                    "To merge new group with existing group, set the groups's "
                    f"Attribute '{LDAP_UNIQUENESS}' to '{uniq}'"
                ),
                source=self._source,
                dn=group_dn,
            ).save()
            return None, None

        self._logger.debug("Synced group", group=ak_group.name, created=created)
        return ak_group, created

    def sync(self, page_data: list) -> int:
        """Iterate over all LDAP Groups and create authentik_core.Group instances"""
        if not self._source.sync_groups:
            self._task.info("Group syncing is disabled for this Source")
            return -1
        group_count = 0
        for entry in page_data:
            group, _ = self.sync_single_record(entry)
            if group:
                group_count += 1
        return group_count
