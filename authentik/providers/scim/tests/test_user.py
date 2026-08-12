"""SCIM User tests"""

import datetime
from json import loads

from django.test import TestCase
from freezegun import freeze_time
from jsonschema import validate
from requests_mock import Mocker

from authentik.blueprints.tests import apply_blueprint
from authentik.core.models import Application, Group, User
from authentik.lib.generators import generate_id
from authentik.lib.sync.outgoing.base import SAFE_METHODS
from authentik.providers.scim.clients.schema import ServiceProviderConfiguration
from authentik.providers.scim.clients.users import SCIMUserClient
from authentik.providers.scim.models import SCIMMapping, SCIMProvider, SCIMProviderUser
from authentik.providers.scim.tasks import scim_sync, scim_sync_objects
from authentik.suse.provider.models import SUSEProviderSyncState
from authentik.tasks.models import Task
from authentik.tenants.models import Tenant


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
    def test_user_create(self, mock: Mocker):
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
        uid = generate_id()
        user = User.objects.create(
            username=uid,
            name=f"{uid} {uid}",
            email=f"{uid}@goauthentik.io",
        )
        self.assertEqual(mock.call_count, 2)
        self.assertEqual(mock.request_history[0].method, "GET")
        self.assertEqual(mock.request_history[1].method, "POST")
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

    @Mocker()
    def test_user_create_custom_schema(self, mock: Mocker):
        """Test user creation with custom schema"""
        schema = SCIMMapping.objects.create(
            name="custom_schema",
            expression="""return {
                "schemas": ["urn:ietf:params:scim:schemas:extension:slack:profile:2.0:User"],
                "urn:ietf:params:scim:schemas:extension:slack:profile:2.0:User": {
                    "startDate": "2024-04-10T00:00:00+0000",
                },
            }""",
        )
        self.provider.property_mappings.add(schema)
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
        uid = generate_id()
        user = User.objects.create(
            username=uid,
            name=f"{uid} {uid}",
            email=f"{uid}@goauthentik.io",
        )
        self.assertEqual(mock.call_count, 2)
        self.assertEqual(mock.request_history[0].method, "GET")
        self.assertEqual(mock.request_history[1].method, "POST")
        self.assertJSONEqual(
            mock.request_history[1].body,
            {
                "schemas": [
                    "urn:ietf:params:scim:schemas:core:2.0:User",
                    "urn:ietf:params:scim:schemas:extension:slack:profile:2.0:User",
                ],
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
                "urn:ietf:params:scim:schemas:extension:slack:profile:2.0:User": {
                    "startDate": "2024-04-10T00:00:00+0000",
                },
            },
        )

    @Mocker()
    def test_user_create_different_provider_same_id(self, mock: Mocker):
        """Test user creation with multiple providers that happen
        to return the same object ID"""
        # Create duplicate provider
        provider: SCIMProvider = SCIMProvider.objects.create(
            name=generate_id(),
            url="https://localhost",
            token=generate_id(),
            exclude_users_service_account=True,
        )
        app: Application = Application.objects.create(
            name=generate_id(),
            slug=generate_id(),
        )
        app.backchannel_providers.add(provider)
        provider.property_mappings.add(
            SCIMMapping.objects.get(managed="goauthentik.io/providers/scim/user")
        )
        provider.property_mappings_group.add(
            SCIMMapping.objects.get(managed="goauthentik.io/providers/scim/group")
        )

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
        uid = generate_id()
        user = User.objects.create(
            username=uid,
            name=f"{uid} {uid}",
            email=f"{uid}@goauthentik.io",
        )
        self.assertEqual(mock.call_count, 4)
        self.assertEqual(mock.request_history[0].method, "GET")
        self.assertEqual(mock.request_history[1].method, "POST")
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

    @Mocker()
    def test_user_create_update(self, mock: Mocker):
        """Test user creation and update"""
        scim_id = generate_id()
        mock: Mocker
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
        mock.put(
            "https://localhost/Users",
            json={
                "id": scim_id,
            },
        )
        uid = generate_id()
        user = User.objects.create(
            username=uid,
            name=f"{uid} {uid}",
            email=f"{uid}@goauthentik.io",
        )
        self.assertEqual(mock.call_count, 2)
        self.assertEqual(mock.request_history[0].method, "GET")
        self.assertEqual(mock.request_history[1].method, "POST")
        body = loads(mock.request_history[1].body)
        with open("schemas/scim-user.schema.json", encoding="utf-8") as schema:
            validate(body, loads(schema.read()))
        self.assertEqual(
            body,
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
                "displayName": f"{uid} {uid}",
                "externalId": user.uid,
                "name": {
                    "familyName": uid,
                    "formatted": f"{uid} {uid}",
                    "givenName": uid,
                },
                "userName": uid,
            },
        )
        # Update user
        user.name = "foo bar"
        user.save()
        self.assertEqual(mock.call_count, 3)
        self.assertEqual(mock.request_history[0].method, "GET")
        self.assertEqual(mock.request_history[1].method, "POST")
        self.assertEqual(mock.request_history[2].method, "PUT")

    @Mocker()
    def test_user_create_delete(self, mock: Mocker):
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
        self.assertEqual(mock.call_count, 2)
        self.assertEqual(mock.request_history[0].method, "GET")
        self.assertEqual(mock.request_history[1].method, "POST")
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
        user.delete()
        self.assertEqual(mock.call_count, 3)
        self.assertEqual(mock.request_history[0].method, "GET")
        self.assertEqual(mock.request_history[1].method, "POST")
        self.assertEqual(mock.request_history[2].method, "DELETE")
        self.assertEqual(mock.request_history[2].url, f"https://localhost/Users/{scim_id}")

    @Mocker()
    def test_sync_task(self, mock: Mocker):
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

    @Mocker()
    def test_sync_task_suse(self, mock: Mocker):
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

        initial_datetime = datetime.datetime(
            year=2000,
            month=7,
            day=12,
            hour=15,
            minute=6,
            second=3,
            tzinfo=datetime.timezone(offset=datetime.timedelta(hours=2)),
        )

        with freeze_time(initial_datetime) as frozen_datetime:
            User.objects.create(
                username=uid,
                name=f"{uid} {uid}",
                email=f"{uid}@goauthentik.io",
            )

            frozen_datetime.tick()

            pages = self.provider.get_paginator(User)
            self.assertEqual(pages.count, 1, "Expect single page")
            self.assertEqual(
                pages.get_page(0).object_list.count(), 1, "Expect one user in first page"
            )

            sync_state = SUSEProviderSyncState.objects.filter(provider_id=self.provider.pk).first()
            self.assertFalse(sync_state, "sync_state should not exist")

            scim_sync.send(self.provider.pk)

            sync_state = SUSEProviderSyncState.objects.filter(provider_id=self.provider.pk).first()

            self.assertTrue(sync_state, "sync_state should exist")
            self.assertEqual(
                sync_state.last_modify_timestamp,
                datetime.datetime(2000, 7, 12, 13, 6, 4, tzinfo=datetime.UTC),
            )

            pages = self.provider.get_paginator(User)
            self.assertEqual(pages.count, 0, "Expect no page after initial sync")

    def test_user_create_dry_run(self):
        """Test user creation (dry_run)"""
        # Update the provider before we start mocking as saving the provider triggers a full sync
        self.provider.dry_run = True
        self.provider.save()
        with Mocker() as mock:
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
            uid = generate_id()
            User.objects.create(
                username=uid,
                name=f"{uid} {uid}",
                email=f"{uid}@goauthentik.io",
            )
            self.assertEqual(mock.call_count, 1, mock.request_history)
            self.assertEqual(mock.request_history[0].method, "GET")

    def test_sync_task_dry_run(self):
        """Test sync tasks"""
        # Update the provider before we start mocking as saving the provider triggers a full sync
        self.provider.dry_run = True
        self.provider.save()
        with Mocker() as mock:
            uid = generate_id()
            mock.get(
                "https://localhost/ServiceProviderConfig",
                json={},
            )
            User.objects.create(
                username=uid,
                name=f"{uid} {uid}",
                email=f"{uid}@goauthentik.io",
            )

            scim_sync.send(self.provider.pk)

            self.assertEqual(mock.call_count, 1)
            for request in mock.request_history:
                self.assertIn(request.method, SAFE_METHODS)
        task = list(
            Task.objects.filter(
                actor_name=scim_sync_objects.actor_name,
                _uid__startswith=self.provider.name,
            ).order_by("-mtime")
        )[1]
        self.assertIsNotNone(task)
        log = task.tasklogs.filter(event="Dropping mutating request due to dry run").first()
        self.assertIsNotNone(log)
        self.assertIsNotNone(log.attributes["url"])
        self.assertIsNotNone(log.attributes["body"])
        self.assertIsNotNone(log.attributes["method"])

    @Mocker()
    def test_user_create_update_noop(self, mock: Mocker):
        """Test user creation and update"""
        scim_id = generate_id()
        mock: Mocker
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
        mock.put(
            "https://localhost/Users",
            json={
                "id": scim_id,
            },
        )
        uid = generate_id()
        user = User.objects.create(
            username=uid,
            name=f"{uid} {uid}",
            email=f"{uid}@goauthentik.io",
        )
        self.assertEqual(mock.call_count, 2)
        self.assertEqual(mock.request_history[0].method, "GET")
        self.assertEqual(mock.request_history[1].method, "POST")
        body = loads(mock.request_history[1].body)
        self.assertEqual(
            body,
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
                "displayName": f"{uid} {uid}",
                "externalId": user.uid,
                "name": {
                    "familyName": uid,
                    "formatted": f"{uid} {uid}",
                    "givenName": uid,
                },
                "userName": uid,
            },
        )
        conn = SCIMProviderUser.objects.filter(user=user).first()
        conn.attributes = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "active": True,
            "emails": [
                {
                    "primary": True,
                    "type": "other",
                    "value": f"{uid}@goauthentik.io",
                }
            ],
            "displayName": f"{uid} {uid}",
            "externalId": user.uid,
            "name": {
                "familyName": uid,
                "formatted": f"{uid} {uid}",
                "givenName": uid,
            },
            "userName": uid,
            "id": scim_id,
        }
        conn.save()
        user.save()
        self.assertEqual(mock.call_count, 2)
        self.assertEqual(mock.request_history[0].method, "GET")
        self.assertEqual(mock.request_history[1].method, "POST")

    @Mocker()
    def test_user_diff_nested_attribute(self, mock: Mocker):
        """Test nested attribute changes are detected without mutating cached data"""
        mock.get("https://localhost/ServiceProviderConfig", json={})
        connection = SCIMProviderUser(
            attributes={
                "urn:ietf:params:scim:schemas:extension:example:2.0:User": {
                    "birthDate": "1990-01-31"
                }
            }
        )

        self.assertTrue(
            SCIMUserClient(self.provider).diff(
                {
                    "urn:ietf:params:scim:schemas:extension:example:2.0:User": {
                        "birthDate": "1991-02-01"
                    }
                },
                connection,
            )
        )
        self.assertEqual(
            connection.attributes["urn:ietf:params:scim:schemas:extension:example:2.0:User"][
                "birthDate"
            ],
            "1990-01-31",
        )

    @Mocker(case_sensitive=True)
    def test_patch_replace_updates(self, mock: Mocker):
        """Test user creation and update (with patch)"""
        sp_config = ServiceProviderConfiguration.default()
        sp_config.patch.supported = True

        scim_id = generate_id()
        mock.get(
            "https://localhost/ServiceProviderConfig",
            json=sp_config.model_dump(mode="json"),
        )
        mock.post(
            "https://localhost/Users",
            json={
                "id": scim_id,
            },
        )
        mock.patch(
            f"https://localhost/Users/{scim_id}",
            json={
                "id": scim_id,
            },
        )
        mock.get(
            f"https://localhost/Users/{scim_id}",
            json={
                "id": scim_id,
            },
        )
        uid = generate_id()
        user = User.objects.create(
            username=uid,
            name=f"{uid} {uid}",
            email=f"{uid}@goauthentik.io",
        )
        self.assertEqual(mock.call_count, 2)
        self.assertEqual(mock.request_history[0].method, "GET")
        self.assertEqual(mock.request_history[0].path, "/ServiceProviderConfig")
        self.assertEqual(mock.request_history[1].method, "POST")
        self.assertEqual(mock.request_history[1].path, "/Users")
        body = loads(mock.request_history[1].body)
        with open("schemas/scim-user.schema.json", encoding="utf-8") as schema:
            validate(body, loads(schema.read()))
        self.assertEqual(
            body,
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
                "displayName": f"{uid} {uid}",
                "externalId": user.uid,
                "name": {
                    "familyName": uid,
                    "formatted": f"{uid} {uid}",
                    "givenName": uid,
                },
                "userName": uid,
            },
        )

        # Update user
        user.name = "foo bar"
        user.is_active = False
        user.save()

        self.assertEqual(mock.call_count, 4)
        self.assertEqual(mock.request_history[2].method, "PATCH")
        self.assertEqual(mock.request_history[2].path, f"/Users/{scim_id}")
        self.assertEqual(mock.request_history[3].method, "GET")
        self.assertEqual(mock.request_history[3].path, f"/Users/{scim_id}")

        scim_user = self.provider.client_for_model(User).to_schema(user, None)
        scim_user.id = scim_id
        payload = scim_user.model_dump(
            mode="json",
            exclude_unset=True,
        )

        self.assertJSONEqual(
            mock.request_history[2].body,
            {
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [
                    {
                        "op": "replace",
                        "value": payload,
                    }
                ],
            },
        )
