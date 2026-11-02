"""Test User Validation (so far, only email)"""

from json import loads

from django.test.utils import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from authentik.core.models import Application
from authentik.core.tests.utils import create_test_admin_user, create_test_user
from authentik.policies.dummy.models import DummyPolicy
from authentik.policies.models import PolicyBinding


class TestApplicationAccessCheck(APITestCase):
    """Test User Email Validation API based on dynamic configuration"""

    def setUp(self) -> None:
        self.user = create_test_admin_user()
        self.allowed: Application = Application.objects.create(
            name="allowed",
            slug="allowed",
            meta_launch_url="https://goauthentik.io/%(username)s",
            open_in_new_tab=True,
        )
        self.denied = Application.objects.create(name="denied", slug="denied")
        PolicyBinding.objects.create(
            target=self.denied,
            policy=DummyPolicy.objects.create(name="deny", result=False, wait_min=1, wait_max=2),
            order=0,
        )

    @override_settings(OVERRIDE_ENDPOINT=dict(core_applications_check_access_retrieve=True))
    def test_check_access_no_superuser(self):
        """Check that an unauthorized user can't use the for_user param"""
        new_user = create_test_user()
        self.client.force_login(new_user)
        response = self.client.get(
            reverse(
                "authentik_api:application-check-access",
                kwargs={"slug": self.allowed.slug},
                query=dict(for_user=self.user.pk),
            )
        )
        self.assertEqual(response.status_code, 200)
        body = loads(response.content.decode())
        self.assertEqual(body["passing"], False)

    @override_settings(OVERRIDE_ENDPOINT=dict(core_applications_check_access_retrieve=True))
    def test_check_access_no_superuser_with_permission(self):
        """Check that an authorized user can use the for_user param"""
        new_user = create_test_user()
        self.client.force_login(new_user)
        new_user.assign_perms_to_managed_role(
            "authentik_core.view_user_applications", obj=self.user
        )
        new_user.assign_perms_to_managed_role("authentik_rbac.access_admin_interface")

        response = self.client.get(
            reverse(
                "authentik_api:application-check-access",
                kwargs={"slug": self.allowed.slug},
                query=dict(for_user=self.user.pk),
            )
        )
        self.assertEqual(response.status_code, 200)
        body = loads(response.content.decode())
        self.assertEqual(body["passing"], True)

        response = self.client.get(
            reverse(
                "authentik_api:application-check-access",
                kwargs={"slug": self.denied.slug},
                query=dict(for_user=self.user.pk),
            )
        )
        self.assertEqual(response.status_code, 200)
        body = loads(response.content.decode())
        self.assertEqual(body["passing"], False)

    @override_settings(OVERRIDE_ENDPOINT=dict(core_applications_check_access_retrieve=True))
    def test_check_access_no_superuser_with_permission_not_same_user(self):
        """Check that an authorized user can use the for_user param for the allowed users"""
        new_user = create_test_user()
        self.client.force_login(new_user)
        new_user.assign_perms_to_managed_role(
            "authentik_core.view_user_applications", obj=self.user
        )
        new_user.assign_perms_to_managed_role("authentik_rbac.access_admin_interface")

        another_user = create_test_user()
        response = self.client.get(
            reverse(
                "authentik_api:application-check-access",
                kwargs={"slug": self.allowed.slug},
                query=dict(for_user=another_user.pk),
            )
        )
        self.assertEqual(response.status_code, 200)
        body = loads(response.content.decode())
        self.assertEqual(body["passing"], False)

        response = self.client.get(
            reverse(
                "authentik_api:application-check-access",
                kwargs={"slug": self.denied.slug},
                query=dict(for_user=another_user.pk),
            )
        )
        self.assertEqual(response.status_code, 200)
        body = loads(response.content.decode())
        self.assertEqual(body["passing"], False)


class TestApplicationList(APITestCase):
    def setUp(self) -> None:
        self.superuser = create_test_admin_user()
        self.user = create_test_user()
        self.other_user = create_test_user()
        self.app_always_allowed = Application.objects.create(
            name="allowed",
            slug="allowed",
            meta_launch_url="https://goauthentik.io/%(username)s",
            open_in_new_tab=True,
        )

        self.app_only_for_second_user = Application.objects.create(
            name="second-app",
            slug="second-app",
            meta_launch_url="https://goauthentik.io/%(username)s",
            open_in_new_tab=True,
        )

        self.app_always_denied = Application.objects.create(name="denied", slug="denied")
        PolicyBinding.objects.create(
            target=self.app_always_denied,
            policy=DummyPolicy.objects.create(name="deny", result=False, wait_min=1, wait_max=2),
            order=0,
        )
        PolicyBinding.objects.create(
            target=self.app_only_for_second_user,
            user=self.other_user,
            order=0,
        )

        # user can see app, but cannot admin it, that's delegated_admin's job.
        self.delegated_admin_app: Application = Application.objects.create(
            name="delegated-admin-app",
            slug="delegated-admin-app",
            meta_launch_url="https://goauthentik.io/%(username)s",
            open_in_new_tab=True,
        )
        PolicyBinding.objects.create(
            target=self.delegated_admin_app,
            user=self.user,
            order=0,
        )
        self.delegated_admin = create_test_user()
        self.delegated_admin.assign_perms_to_managed_role("authentik_core.view_user_applications")
        self.delegated_admin.assign_perms_to_managed_role("authentik_rbac.access_admin_interface")

    def test_upstream_plain_list_behavior(self):
        self.client.force_login(self.user)

        with self.assertNumQueries(46):
            response = self.client.get(reverse("authentik_api:application-list"))
            self.assertEqual(response.status_code, 200)

        with self.assertNumQueries(26):
            response = self.client.get(reverse("authentik_api:application-list"))
            self.assertEqual(response.status_code, 200)

    @override_settings(OVERRIDE_ENDPOINT=dict(core_applications_list=True))
    def test_list_new_cache_less_sql_queries(self):
        self.client.force_login(self.user)

        expected_app_ids = {
            str(app.pk) for app in [self.app_always_allowed, self.delegated_admin_app]
        }

        with self.assertNumQueries(46):
            response = self.client.get(reverse("authentik_api:application-list"))
            self.assertEqual(response.status_code, 200)
            returned_app_ids = {i["pk"] for i in response.json()["results"]}
            assert expected_app_ids == returned_app_ids, "Allowed apps differ, permissions broke."

        with self.assertNumQueries(26):
            response = self.client.get(reverse("authentik_api:application-list"))
            self.assertEqual(response.status_code, 200)
            returned_app_ids = {i["pk"] for i in response.json()["results"]}
            assert expected_app_ids == returned_app_ids, "Allowed apps differ, permissions broke."

    @override_settings(OVERRIDE_ENDPOINT=dict(core_applications_list=True))
    def test_list_app_for_other_user(self):
        self.client.force_login(self.delegated_admin)

        expected_app_ids = {
            str(app.pk) for app in [self.app_always_allowed, self.app_only_for_second_user]
        }

        with self.assertNumQueries(49):
            response = self.client.get(
                reverse("authentik_api:application-list", query=dict(for_user=self.other_user.pk))
            )
            self.assertEqual(response.status_code, 200)
            returned_app_ids = {i["pk"] for i in response.json()["results"]}
            assert expected_app_ids == returned_app_ids, "Allowed apps differ, permissions broke."

        with self.assertNumQueries(29):
            response = self.client.get(
                reverse("authentik_api:application-list", query=dict(for_user=self.other_user.pk))
            )
            self.assertEqual(response.status_code, 200)
            returned_app_ids = {i["pk"] for i in response.json()["results"]}
            assert expected_app_ids == returned_app_ids, "Allowed apps differ, permissions broke."

    @override_settings(OVERRIDE_ENDPOINT=dict(core_applications_list=True))
    def test_list_app_for_other_when_superuser(self):
        self.client.force_login(self.superuser)

        expected_app_ids = {
            str(app.pk) for app in [self.app_always_allowed, self.app_only_for_second_user]
        }

        with self.assertNumQueries(48):
            response = self.client.get(
                reverse("authentik_api:application-list", query=dict(for_user=self.other_user.pk))
            )
            self.assertEqual(response.status_code, 200)
            returned_app_ids = {i["pk"] for i in response.json()["results"]}
            assert expected_app_ids == returned_app_ids, "Allowed apps differ, permissions broke."

        with self.assertNumQueries(28):
            response = self.client.get(
                reverse("authentik_api:application-list", query=dict(for_user=self.other_user.pk))
            )
            self.assertEqual(response.status_code, 200)
            returned_app_ids = {i["pk"] for i in response.json()["results"]}
            assert expected_app_ids == returned_app_ids, "Allowed apps differ, permissions broke."

    @override_settings(OVERRIDE_ENDPOINT=dict(core_applications_list=True))
    def test_list_app_superuser(self):
        self.client.force_login(self.superuser)

        expected_app_ids = {
            str(app.pk)
            for app in [
                self.app_always_allowed,
                self.app_only_for_second_user,
                self.app_always_denied,
                self.delegated_admin_app,
            ]
        }

        with self.assertNumQueries(24):
            response = self.client.get(
                reverse("authentik_api:application-list", query=dict(superuser_full_list="true"))
            )
            self.assertEqual(response.status_code, 200)
            returned_app_ids = {i["pk"] for i in response.json()["results"]}
            assert expected_app_ids == returned_app_ids, "Allowed apps differ, permissions broke."

        with self.assertNumQueries(25):
            response = self.client.get(
                reverse("authentik_api:application-list", query=dict(superuser_full_list="true"))
            )
            self.assertEqual(response.status_code, 200)
            returned_app_ids = {i["pk"] for i in response.json()["results"]}
            assert expected_app_ids == returned_app_ids, "Allowed apps differ, permissions broke."
