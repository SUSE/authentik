"""SCIM User tests"""

from django.test import TestCase, override_settings
from requests_mock import Mocker

from authentik.blueprints.tests import apply_blueprint
from authentik.core.models import Application, Group, User
from authentik.lib.generators import generate_id
from authentik.lib.sync.outgoing.signals import sync_outgoing_inhibit_dispatch
from authentik.providers.scim.models import SCIMMapping, SCIMProvider, SCIMProviderUser
from authentik.providers.scim.tasks import scim_sync
from authentik.suse.providers.scim.clients.users import SUSE_SCIM_LAST_UPDATED_ATTR
from authentik.tenants.models import Tenant


@override_settings(USE_SUSE_SCIM_CLIENT=True)
class SCIMUserTests(TestCase):
    """SCIM User tests"""

    @apply_blueprint("system/providers-scim.yaml")
    def setUp(self) -> None:
        # Delete all users and groups as the mocked HTTP responses only return one ID
        # which will cause errors with multiple users
        Tenant.objects.update(avatars="none")
        User.objects.all().exclude_anonymous().delete()
        Group.objects.all().delete()
        self.provider: SCIMProvider = SCIMProvider.objects.create(
            name=generate_id(),
            url="https://localhost",
            token=generate_id(),
            exclude_users_service_account=True,
        )
        self.app: Application = Application.objects.create(
            name=generate_id(),
            slug=generate_id(),
        )
        self.app.backchannel_providers.add(self.provider)
        self.provider.property_mappings.add(
            SCIMMapping.objects.get(managed="goauthentik.io/providers/scim/user")
        )
        self.provider.property_mappings_group.add(
            SCIMMapping.objects.get(managed="goauthentik.io/providers/scim/group")
        )

    @Mocker()
    def test_user_create_orphan(self, mock: Mocker):
        """Test user creation"""
        scim_id = generate_id()
        mock.get(
            "https://localhost/ServiceProviderConfig",
            json={},
        )
        mock.post(
            "https://localhost/Users",
            json={
                "id": scim_id,
            },
        )

        mock.delete(f"https://localhost/Users/{scim_id}", status_code=204)
        uid = generate_id()
        user = User.objects.create(
            username=uid,
            name=f"{uid} {uid}",
            email=f"{uid}@goauthentik.io",
        )

        with sync_outgoing_inhibit_dispatch():
            self.provider.filter_group = Group.objects.create(name="filter_group")
            self.provider.filter_group.users.add(user)
            self.provider.save()

        group_id = generate_id()
        mock.post(
            "https://localhost/Groups",
            json={
                "id": group_id,
            },
        )
        mock.patch(
            f"https://localhost/Groups/{group_id}",
            json={
                "id": group_id,
            },
        )

        self.assertEqual(mock.call_count, 2)
        self.assertEqual(mock.request_history[0].method, "GET")
        self.assertEqual(mock.request_history[0].path, "/serviceproviderconfig")
        self.assertEqual(mock.request_history[1].method, "POST")
        self.assertEqual(mock.request_history[1].path, "/users")
        self.assertJSONEqual(
            mock.request_history[1].body,
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                "active": True,
                "emails": [
                    {
                        "primary": True,
                        "type": "other",
                        "value": f"{uid}@goauthentik.io",
                    }
                ],
                "externalId": user.uid,
                "name": {
                    "familyName": uid,
                    "formatted": f"{uid} {uid}",
                    "givenName": uid,
                },
                "displayName": f"{uid} {uid}",
                "userName": uid,
            },
        )

        connections = self.provider.client_for_model(User).connection_type.objects.all()
        self.assertEqual(connections.count(), 1)

        with sync_outgoing_inhibit_dispatch():
            self.provider.filter_group.users.remove(user)
            self.provider.filter_group.save()

        scim_sync.send(self.provider.pk)

        connections = self.provider.client_for_model(User).connection_type.objects.all()
        self.assertEqual(connections.count(), 0)

        self.assertEqual(mock.call_count, 5)
        self.assertEqual(mock.request_history[4].method, "DELETE")
        self.assertEqual(mock.request_history[4].url, f"https://localhost/Users/{scim_id}")

    @Mocker()
    def test_sync_task_incremental(self, mock: Mocker):
        """Test sync tasks"""
        user_scim_id = generate_id()
        group_scim_id = generate_id()
        uid = generate_id()
        mock.get(
            "https://localhost/ServiceProviderConfig",
            json={},
        )
        mock.post(
            "https://localhost/Users",
            json={
                "id": user_scim_id,
            },
        )
        mock.put(
            f"https://localhost/Users/{user_scim_id}",
            json={
                "id": user_scim_id,
            },
        )
        mock.post(
            "https://localhost/Groups",
            json={
                "id": group_scim_id,
            },
        )

        user = User.objects.create(
            username=uid,
            name=f"{uid} {uid}",
            email=f"{uid}@goauthentik.io",
        )

        scim_sync.send(self.provider.pk)

        self.assertEqual(mock.call_count, 3)
        self.assertEqual(mock.request_history[0].method, "GET")
        self.assertEqual(mock.request_history[1].method, "POST")
        self.assertEqual(mock.request_history[2].method, "PUT")
        self.assertJSONEqual(
            mock.request_history[1].body,
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                "active": True,
                "emails": [
                    {
                        "primary": True,
                        "type": "other",
                        "value": f"{uid}@goauthentik.io",
                    }
                ],
                "externalId": user.uid,
                "name": {
                    "familyName": uid,
                    "formatted": f"{uid} {uid}",
                    "givenName": uid,
                },
                "displayName": f"{uid} {uid}",
                "userName": uid,
            },
        )

        conn = SCIMProviderUser.objects.filter(user=user).first()
        self.assertEqual(
            conn.attributes[SUSE_SCIM_LAST_UPDATED_ATTR], user.last_updated.isoformat()
        )

        # run the second full sync
        scim_sync.send(self.provider.pk)

        # Should not have called anything else over http
        self.assertEqual(mock.call_count, 3)

        conn = SCIMProviderUser.objects.filter(user=user).first()
        self.assertEqual(
            conn.attributes[SUSE_SCIM_LAST_UPDATED_ATTR], user.last_updated.isoformat()
        )
