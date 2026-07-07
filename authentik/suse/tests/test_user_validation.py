"""Test User Validation (so far, only email)"""

from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APITestCase

from authentik.core.models import User
from authentik.core.tests.utils import create_test_admin_user, create_test_user
from authentik.lib.generators import generate_id
from authentik.rbac.models import Role

# AUTHENTIK_SUSE__CONSTRAINTS__EMAIL=
# $(printf '{"test-role-allow-corp-create": {"allow": ["corp.example.com"]}}' | base64 -w0)
TEST_CONSTRAINTS = {
    "email": {
        "restricted_domains": ["corp.example.com"],
        "roles_domains": {"test-role-allow-corp-create": {"allow": ["corp.example.com"]}},
    }
}

EMPTY_CONSTRAINTS = {
    "email": {
        "restricted_domains": [],
        "roles_domains": {},
    }
}


class TestUserEmailValidation(APITestCase):
    """Test User Email Validation API based on dynamic configuration"""

    def setUp(self) -> None:
        super().setUp()

        # Standard admin user (no explicit roles)
        self.admin_user = create_test_admin_user()

        # Standard user with basic user management permissions
        self.manager_user = create_test_user()
        self.manager_user.assign_perms_to_managed_role("authentik_core.add_user")
        self.manager_user.assign_perms_to_managed_role("authentik_core.change_user")
        self.manager_user.assign_perms_to_managed_role(
            "authentik_core.view_user"
        )  # needed for PATCH

        # User with user management permissions AND the specific bypass role
        self.bypass_role = Role.objects.create(name="test-role-allow-corp-create")
        self.bypass_user = create_test_user()
        self.bypass_user.assign_perms_to_managed_role("authentik_core.add_user")
        self.bypass_user.roles.add(self.bypass_role)

    @patch.dict("authentik.core.api.users.CONSTRAINTS", EMPTY_CONSTRAINTS, clear=True)
    def test_missing_configuration_blocks_all(self):
        """Test that if configuration is missing/empty, all creations fail safely"""
        self.client.force_login(self.manager_user)
        response = self.client.post(
            reverse("authentik_api:user-list"),
            data={
                "username": generate_id(),
                "name": "Test User",
                "email": "user@anything.com",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)
        self.assertEqual(
            response.data["email"][0],
            "Failed to read domain restrictions. This is an operational problem.",
        )

    @patch.dict("authentik.core.api.users.CONSTRAINTS", TEST_CONSTRAINTS, clear=True)
    def test_unrestricted_domain_allowed(self):
        """Test that a domain not in the restricted list passes validation"""
        self.client.force_login(self.manager_user)
        response = self.client.post(
            reverse("authentik_api:user-list"),
            data={
                "username": generate_id(),
                "name": "Public User",
                "email": "user@gmail.com",
            },
        )
        self.assertEqual(response.status_code, 201)

    @patch.dict("authentik.core.api.users.CONSTRAINTS", TEST_CONSTRAINTS, clear=True)
    def test_restricted_domain_blocked_without_role(self):
        """Test that a restricted domain is blocked for users without the role"""
        self.client.force_login(self.manager_user)
        response = self.client.post(
            reverse("authentik_api:user-list"),
            data={
                "username": generate_id(),
                "name": "Corp User",
                "email": "user@corp.example.com",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)
        self.assertEqual(
            response.data["email"][0], "You are not authorized to set this email address."
        )

    @patch.dict("authentik.core.api.users.CONSTRAINTS", TEST_CONSTRAINTS, clear=True)
    def test_restricted_domain_allowed_with_role(self):
        """Test that a restricted domain is allowed if the caller has the role"""
        self.client.force_login(self.bypass_user)
        response = self.client.post(
            reverse("authentik_api:user-list"),
            data={
                "username": generate_id(),
                "name": "Authorized Corp User",
                "email": "user@corp.example.com",
            },
        )
        self.assertEqual(response.status_code, 201)

    @patch.dict("authentik.core.api.users.CONSTRAINTS", TEST_CONSTRAINTS, clear=True)
    def test_admin_blocked_without_role(self):
        """Test that even an admin is blocked if they lack the explicit bypass role"""
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse("authentik_api:user-list"),
            data={
                "username": generate_id(),
                "name": "Admin Creating Corp User",
                "email": "user@corp.example.com",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)

    @patch.dict("authentik.core.api.users.CONSTRAINTS", TEST_CONSTRAINTS, clear=True)
    def test_update_other_field_skips_validation(self):
        """Test that updating a different field on an existing user skips email validation"""
        # Create a user directly in the database with a restricted email
        target_user = User.objects.create(
            username=generate_id(), name="Old Name", email="legacy@corp.example.com"
        )

        # Attempt to patch the name using a user WITHOUT the bypass role
        self.client.force_login(self.manager_user)
        response = self.client.patch(
            reverse("authentik_api:user-detail", kwargs={"pk": target_user.pk}),
            data={
                "name": "New Name",
            },
        )
        # Should succeed because the email itself wasn't modified
        self.assertEqual(response.status_code, 200)
        target_user.refresh_from_db()
        self.assertEqual(target_user.name, "New Name")

    @patch.dict("authentik.core.api.users.CONSTRAINTS", TEST_CONSTRAINTS, clear=True)
    def test_update_other_field_including_email_skips_validation(self):
        """Test that updating a different field on an existing user skips email validation,
        even if email is included in the payload"""
        # Create a user directly in the database with a restricted email
        target_user = User.objects.create(
            username=generate_id(), name="Old Name", email="legacy@corp.example.com"
        )

        # Attempt to patch the name using a user WITHOUT the bypass role
        self.client.force_login(self.manager_user)
        response = self.client.patch(
            reverse("authentik_api:user-detail", kwargs={"pk": target_user.pk}),
            data={
                "name": "New Name",
                "email": "legacy@corp.example.com",
            },
        )
        # Should succeed because the email itself wasn't modified
        self.assertEqual(response.status_code, 200)
        target_user.refresh_from_db()
        self.assertEqual(target_user.name, "New Name")
