"""Sync LDAP Users into authentik"""

from django.core.exceptions import FieldError
from django.db.utils import IntegrityError
from ldap3 import SUBTREE

from authentik.core.expression.exceptions import (
    PropertyMappingExpressionException,
    SkipObjectException,
)
from authentik.core.models import User
from authentik.events.models import Event, EventAction
from authentik.lib.sync.outgoing.exceptions import StopSync
from authentik.sources.ldap.models import (
    LDAP_UNIQUENESS,
    UserLDAPSourceConnection,
    flatten,
)
from authentik.sources.ldap.sync.vendor.freeipa import FreeIPA
from authentik.sources.ldap.sync.vendor.ms_ad import MicrosoftActiveDirectory


class UserSynchronizer:
    def get_filter_and_base(
        self, attribute_name=None, attribute_value=None, search_base=None, dn=None
    ):
        return super().get_filter_and_base(
            search_base=search_base or self.base_dn_users,
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
            search_base = self.base_dn_users
        if not search_filter:
            search_filter = self._source.user_object_filter
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
        if not self._source.sync_users:
            self._task.info("User syncing is disabled for this Source")
            return iter(())

        search_filter = self._source.user_object_filter
        if since:
            search_filter = self.add_modify_timestamp_filter(search_filter, since)

        return self.search_paginator(
            search_base=self.base_dn_users,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=self.get_ldap_attributes(),
            **kwargs,
        )

    # sync_single_record (self, user : dict) -> tuple[Optional[User], Optional[bool]]
    def sync_single_record(self, user_entry: dict):
        """Process a single ldap record into a User"""
        if (attributes := self.get_attributes(user_entry)) is None:
            return None, None

        user_dn = flatten(user_entry.get("entryDN", user_entry.get("dn")))
        if not (uniq := self.get_identifier(attributes)):
            self._task.info(
                f"Uniqueness field not found/not set in attributes: '{user_dn}'",
                attributes=list(attributes.keys()),
                dn=user_dn,
            )
            return None, None

        try:
            defaults = {
                k: flatten(v)
                for k, v in self.mapper.build_object_properties(
                    object_type=User,
                    manager=self.manager,
                    user=None,
                    request=None,
                    dn=user_dn,
                    ldap=attributes,
                ).items()
            }
            self._logger.debug("Writing user with attributes", **defaults)
            if "username" not in defaults:
                raise IntegrityError("Username was not set by propertymappings")
            ak_user, created = User.update_or_create_attributes(
                {f"attributes__{LDAP_UNIQUENESS}": uniq}, defaults
            )
            if not UserLDAPSourceConnection.objects.filter(source=self._source, identifier=uniq):
                UserLDAPSourceConnection.objects.create(
                    source=self._source, user=ak_user, identifier=uniq
                )
        except PropertyMappingExpressionException as exc:
            raise StopSync(exc, None, exc.mapping) from exc
        except SkipObjectException:
            return None, None
        except (IntegrityError, FieldError, TypeError, AttributeError) as exc:
            Event.new(
                EventAction.CONFIGURATION_ERROR,
                message=(
                    f"Failed to create user: {str(exc)} "
                    "To merge new user with existing user, set the user's "
                    f"Attribute '{LDAP_UNIQUENESS}' to '{uniq}'"
                ),
                source=self._source,
                dn=user_dn,
            ).save()
            return None, None

        self._logger.debug("Synced User", user=ak_user.username, created=created)

        MicrosoftActiveDirectory(self._source, self._task).sync(attributes, ak_user, created)
        FreeIPA(self._source, self._task).sync(attributes, ak_user, created)

        return ak_user, created

    def sync(self, page_data: list) -> int:
        """Iterate over all LDAP Users and create authentik_core.User instances"""
        if not self._source.sync_users:
            self._task.info("User syncing is disabled for this Source")
            return -1
        user_count = 0
        for entry in page_data:
            user, _ = self.sync_single_record(entry)
            if user:
                user_count += 1

        return user_count
