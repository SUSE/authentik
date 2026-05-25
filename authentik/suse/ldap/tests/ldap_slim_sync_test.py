"""LDAP Source tests"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db.models import Q
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from authentik.blueprints.tests import apply_blueprint
from authentik.lib.generators import generate_key
from authentik.sources.ldap.models import (
    LDAPSource,
    LDAPSourcePropertyMapping,
)
from authentik.sources.ldap.tasks import (
    ldap_slim_sync_all_users,
)
from authentik.sources.ldap.tests.mock_389ds import mock_389ds_connection
from authentik.suse.ldap.tasks import (
    CACHE_KEY_LAST_SYNC_PREFIX,
    CACHE_KEY_PREFIX,
)

LDAP_PASSWORD = generate_key()


class LDAPSlimSyncTests(TestCase):
    """LDAP Sync tests"""

    @apply_blueprint("system/sources-ldap.yaml")
    def setUp(self):
        self.source: LDAPSource = LDAPSource.objects.create(
            name="ldap [since=hours=96]",
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

    def test_full_sync(self):
        connection = MagicMock(return_value=mock_389ds_connection(LDAP_PASSWORD))
        with patch("authentik.sources.ldap.models.LDAPSource.connection", connection):
            ldap_slim_sync_all_users.send(self.source.slug)
            expected_usernames = sorted(["unique-test-username", "user0_sn", "unique-test2222"])

            after_user_id_list = sorted(
                self.source.user_set.all().values_list("username", flat=True)
            )
            self.assertListEqual(
                after_user_id_list,
                expected_usernames,
                "User count does not match directory count",
            )

    def test_partial_sync(self):
        # fake that the LDAP sync already ran 15 hours ago
        cache.set(
            CACHE_KEY_LAST_SYNC_PREFIX + self.source.slug, timezone.now() - timedelta(hours=15)
        )

        connection = MagicMock(return_value=mock_389ds_connection(LDAP_PASSWORD))
        with patch("authentik.sources.ldap.models.LDAPSource.connection", connection):
            ldap_slim_sync_all_users.send(self.source.slug)
            expected_usernames = sorted(["unique-test2222"])

            after_user_id_list = sorted(
                self.source.user_set.all().values_list("username", flat=True)
            )
            self.assertListEqual(
                after_user_id_list,
                expected_usernames,
                "User count does not match directory count",
            )

    def test_partial_sync_explicit_since(self):
        connection = MagicMock(return_value=mock_389ds_connection(LDAP_PASSWORD))
        with patch("authentik.sources.ldap.models.LDAPSource.connection", connection):
            ldap_slim_sync_all_users.send(
                self.source.slug, since=timezone.now() - timedelta(hours=15)
            )
            expected_usernames = sorted(["unique-test2222"])

            after_user_id_list = sorted(
                self.source.user_set.all().values_list("username", flat=True)
            )
            self.assertListEqual(
                after_user_id_list,
                expected_usernames,
                "User count does not match directory count",
            )

    def test_cache_composition(self):
        connection = MagicMock(return_value=mock_389ds_connection(LDAP_PASSWORD))
        with patch("authentik.sources.ldap.models.LDAPSource.connection", connection):
            with freeze_time():
                now = timezone.now()

                ldap_slim_sync_all_users.send(self.source.slug, preserve_cache=True)

                cache_keys = cache.keys(CACHE_KEY_PREFIX + "*")
                self.assertTrue(len(cache_keys) > 0, "Cache was wiped out")

                for page_cache_key in cache_keys:
                    entries_page = cache.get(page_cache_key)
                    self.assertTrue(len(entries_page) > 0, "Cached page was empty")

                    for entry in entries_page:
                        self.assertTrue("dn" in entry)
                        # All user records in the mock have a cn
                        self.assertFalse("cn" in entry["attributes"])

                since = cache.get(CACHE_KEY_LAST_SYNC_PREFIX + self.source.slug)
                self.assertTrue(since is not None, "Cache was wiped out")

                self.assertTrue(since == now, "Clocks drifted, this should never happen...")
