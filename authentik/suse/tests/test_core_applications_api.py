"""Test User Validation (so far, only email)"""

from json import loads

from django.test.utils import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from authentik.core.models import Application
from authentik.core.tests.utils import create_test_admin_user, create_test_user
from authentik.policies.dummy.models import DummyPolicy
from authentik.policies.models import PolicyBinding


class TestUserEmailValidation(APITestCase):
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
        self.assertEqual(response.status_code, 403)

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
        self.assertEqual(response.status_code, 400)
        response = self.client.get(
            reverse(
                "authentik_api:application-check-access",
                kwargs={"slug": self.denied.slug},
                query=dict(for_user=another_user.pk),
            )
        )
        self.assertEqual(response.status_code, 400)
