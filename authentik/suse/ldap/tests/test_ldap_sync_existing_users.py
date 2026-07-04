"""LDAP Source tests"""

from unittest.mock import MagicMock, patch

from django.db.models import Q
from django.test import TestCase

from authentik.blueprints.tests import apply_blueprint
from authentik.core.models import User
from authentik.lib.generators import generate_key
from authentik.sources.ldap.models import (
    LDAPSource,
    LDAPSourcePropertyMapping,
)
from authentik.sources.ldap.sync.users import UserLDAPSynchronizer
from authentik.sources.ldap.tasks import (
    ldap_sync_existing_users,
)
from authentik.sources.ldap.tests.mock_389ds import mock_389ds_connection
from authentik.tasks.models import Task

LDAP_PASSWORD = generate_key()


class LDAPSyncExistingUsersTests(TestCase):
    """LDAP Sync tests"""

    @apply_blueprint("system/sources-ldap.yaml")
    def setUp(self):
        self.source: LDAPSource = LDAPSource.objects.create(
            name="ldap [JIT][uid=uid][gid=cn]",
            slug="ldap",
            base_dn="dc=goauthentik,dc=io",
            additional_user_dn="ou=users",
            additional_group_dn="ou=groups",
            # Matches the uid in mock_389ds.py
            object_uniqueness_field="uid",
        )
        self.source.user_property_mappings.set(
            LDAPSourcePropertyMapping.objects.filter(
                Q(managed__startswith="goauthentik.io/sources/ldap/default")
                | Q(managed__startswith="goauthentik.io/sources/ldap/openldap-uid")
            )
        )

    def test_sync_source_users_no_delete(self):
        # Matches the uid in mock_389ds.py
        connection = MagicMock(return_value=mock_389ds_connection(LDAP_PASSWORD))
        with patch("authentik.sources.ldap.models.LDAPSource.connection", connection):
            # Sync all users
            UserLDAPSynchronizer(self.source, Task()).sync_full()

            before_user_id_list = sorted(self.source.user_set.all().values_list("pk", flat=True))
            # run the task
            ldap_sync_existing_users.send(self.source.pk)
            after_user_id_list = sorted(self.source.user_set.all().values_list("pk", flat=True))

            # see the user deleted
            self.assertListEqual(
                before_user_id_list,
                after_user_id_list,
                "User count differed after an idempotent sync",
            )

    def test_sync_source_users_deleted(self):
        # Matches the uid in mock_389ds.py
        self.source.delete_not_found_objects = True
        self.source.save()
        connection = MagicMock(return_value=mock_389ds_connection(LDAP_PASSWORD))
        with patch("authentik.sources.ldap.models.LDAPSource.connection", connection):
            # Sync all users
            UserLDAPSynchronizer(self.source, Task()).sync_full()

            # "delete" a user from LDAP (change the DN to something random)
            u = User.objects.filter(attributes__distinguishedName__isnull=False).first()
            u.attributes["distinguishedName"] = f"uid={u.username},dc=non-existing-corp,dc=bar"
            u.save()

            # run the task
            ldap_sync_existing_users.send(self.source.pk)

            # see the user deleted
            after_user_id_list = sorted(self.source.user_set.all().values_list("pk", flat=True))
            self.assertTrue(u.id not in after_user_id_list, "User was not deleted")
