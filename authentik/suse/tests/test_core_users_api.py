"""Test User Validation (so far, only email)"""

from django.test.utils import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from authentik.core.tests.utils import (
    create_test_admin_user,
    create_test_brand,
    create_test_flow,
    create_test_user,
)
from authentik.flows.models import FlowAuthenticationRequirement, FlowDesignation


class TestCoreUsersPasswordPermissions(APITestCase):
    """Test User Email Validation API based on dynamic configuration"""

    def setUp(self) -> None:
        self.admin = create_test_admin_user()
        self.user = create_test_user()
        flow = create_test_flow(
            FlowDesignation.RECOVERY,
            authentication=FlowAuthenticationRequirement.REQUIRE_UNAUTHENTICATED,
        )
        brand = create_test_brand()
        brand.flow_recovery = flow
        brand.save()

    # Upstream behavior
    def test_original_recovery_link(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("authentik_api:user-recovery", kwargs={"pk": self.user.pk})
        )
        self.assertEqual(response.status_code, 403)

        self.user.assign_perms_to_managed_role("authentik_core.add_user")
        self.user.assign_perms_to_managed_role("authentik_core.reset_user_password")

        response = self.client.post(
            reverse("authentik_api:user-recovery", kwargs={"pk": self.user.pk})
        )
        self.assertEqual(response.status_code, 200)

    def test_original_set_password(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("authentik_api:user-set-password", kwargs={"pk": self.user.pk})
        )
        self.assertEqual(response.status_code, 403)

        self.user.assign_perms_to_managed_role("authentik_core.view_user")
        self.user.assign_perms_to_managed_role("authentik_core.reset_user_password")

        response = self.client.post(
            reverse("authentik_api:user-set-password", kwargs={"pk": self.user.pk}),
            data=dict(password="foo-bar-baz"),
        )
        self.assertEqual(response.status_code, 204)

    # Custom behavior
    @override_settings(OVERRIDE_ENDPOINT=dict(core_users_recovery_create=True))
    def test_suse_recovery_link(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("authentik_api:user-recovery", kwargs={"pk": self.user.pk})
        )
        self.assertEqual(response.status_code, 403)

        self.user.assign_perms_to_managed_role("authentik_core.add_user")
        self.user.assign_perms_to_managed_role("authentik_core.reset_user_password")

        response = self.client.post(
            reverse("authentik_api:user-recovery", kwargs={"pk": self.user.pk})
        )
        # same conditions as upstream, result in 403
        self.assertEqual(response.status_code, 403)

        # we require view user + reset_user
        self.user.remove_all_perms_from_managed_role()
        self.user.assign_perms_to_managed_role("authentik_core.view_user")
        self.user.assign_perms_to_managed_role("authentik_core.reset_user_password")
        response = self.client.post(
            reverse("authentik_api:user-recovery", kwargs={"pk": self.user.pk})
        )
        self.assertEqual(response.status_code, 200)

    @override_settings(OVERRIDE_ENDPOINT=dict(core_users_set_password_create=True))
    def test_suse_set_password(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("authentik_api:user-set-password", kwargs={"pk": self.user.pk})
        )
        self.assertEqual(response.status_code, 403)

        self.user.assign_perms_to_managed_role("authentik_core.view_user")
        self.user.assign_perms_to_managed_role("authentik_core.reset_user_password")

        response = self.client.post(
            reverse("authentik_api:user-set-password", kwargs={"pk": self.user.pk}),
            data=dict(password="foo-bar-baz"),
        )
        # same conditions as upstream result in 403
        self.assertEqual(response.status_code, 403)

        # we require view, update & reset user password
        self.user.assign_perms_to_managed_role("authentik_core.change_user")
        response = self.client.post(
            reverse("authentik_api:user-set-password", kwargs={"pk": self.user.pk}),
            data=dict(password="foo-bar-baz"),
        )
        self.assertEqual(response.status_code, 204)

    @override_settings(OVERRIDE_ENDPOINT=dict(core_users_set_password_create=True))
    def test_suse_update_user_no_set_password(self):
        """Test that user details can be changed, but not the password"""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("authentik_api:user-set-password", kwargs={"pk": self.user.pk})
        )
        self.assertEqual(response.status_code, 403)

        self.user.assign_perms_to_managed_role("authentik_core.view_user")

        response = self.client.post(
            reverse("authentik_api:user-set-password", kwargs={"pk": self.user.pk}),
            data=dict(password="foo-bar-baz"),
        )
        # same conditions as upstream result in 403
        self.assertEqual(response.status_code, 403)

        # we require view, update & reset user password
        self.user.assign_perms_to_managed_role("authentik_core.change_user")
        response = self.client.post(
            reverse("authentik_api:user-set-password", kwargs={"pk": self.user.pk}),
            data=dict(password="foo-bar-baz"),
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.patch(
            reverse("authentik_api:user-detail", kwargs={"pk": self.user.pk}),
            data=dict(name="foo-bar-baz"),
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("authentik_api:user-set-password", kwargs={"pk": self.user.pk}),
            data=dict(password="foo-bar-baz"),
        )
        self.assertEqual(response.status_code, 403)


class TestCoreUsersMergeAttributesAPI(APITestCase):
    """Test User Email Validation API based on dynamic configuration"""

    def setUp(self) -> None:
        self.admin = create_test_admin_user()
        self.user = create_test_user()
        self.user.attributes = dict(foo="bar", bar="baz")
        self.user.save()

    # Upstream behavior
    def test_original_update_attributes(self):
        self.client.force_login(self.admin)

        response = self.client.put(
            reverse("authentik_api:user-detail", kwargs={"pk": self.user.pk}),
            data=dict(
                attributes=dict(qux="quax"),
                username=self.user.username,
                name=self.user.name,
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        assert self.user.attributes.get("bar") is None, "Attribute 'baz' didn't get overwritten"

    def test_original_patch_attributes(self):
        self.client.force_login(self.admin)

        response = self.client.patch(
            reverse("authentik_api:user-detail", kwargs={"pk": self.user.pk}),
            data=dict(attributes=dict(qux="quax")),
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        assert self.user.attributes.get("bar") is None, "Attribute 'baz' didn't get overwritten"

    # SUSE Behavior
    @override_settings(OVERRIDE_ENDPOINT=dict(core_users_update=True))
    def test_update_attributes(self):
        self.client.force_login(self.admin)

        response = self.client.put(
            reverse("authentik_api:user-detail", kwargs={"pk": self.user.pk}),
            data=dict(
                attributes=dict(qux="quax"),
                username=self.user.username,
                name=self.user.name,
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        assert self.user.attributes.get("bar") == "baz", "Attribute 'baz' got lost after PUT!"

    @override_settings(OVERRIDE_ENDPOINT=dict(core_users_update=True))
    def test_update_attributes_wants_to_replace(self):
        self.client.force_login(self.admin)

        response = self.client.put(
            reverse(
                "authentik_api:user-detail",
                kwargs={"pk": self.user.pk},
                query=dict(replace_attributes="true"),
            ),
            data=dict(
                attributes=dict(qux="quax"),
                username=self.user.username,
                name=self.user.name,
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        new_bar = self.user.attributes.get("bar")
        assert (
            new_bar is None
        ), "Attribute 'baz' was not replaced after PUT + replace_attributes=true!"

        qux = self.user.attributes.get("qux")
        assert qux == "quax", "Attribute 'qux' did not update"

    @override_settings(OVERRIDE_ENDPOINT=dict(core_users_partial_update=True))
    def test_patch_attributes(self):
        self.client.force_login(self.admin)

        response = self.client.patch(
            reverse("authentik_api:user-detail", kwargs={"pk": self.user.pk}),
            data=dict(attributes=dict(qux="quax")),
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        new_bar = self.user.attributes.get("bar")
        assert new_bar == "baz", "Attribute 'bar' was replaced after PATCH!"

        qux = self.user.attributes.get("qux")
        assert qux == "quax", "Attribute 'qux' did not update"

    @override_settings(OVERRIDE_ENDPOINT=dict(core_users_partial_update=True))
    def test_patch_attributes_wants_to_replace(self):
        self.client.force_login(self.admin)

        response = self.client.patch(
            reverse(
                "authentik_api:user-detail",
                kwargs={"pk": self.user.pk},
                query=dict(replace_attributes="true"),
            ),
            data=dict(attributes=dict(qux="quax")),
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        new_bar = self.user.attributes.get("bar")
        assert (
            new_bar is None
        ), "Attribute 'bar' was not replaced after PATCH + replace_attributes=true!"

        qux = self.user.attributes.get("qux")
        assert qux == "quax", "Attribute 'qux' did not update"

    # SUSE Behavior cross-checking (enabling PATCH but not PUT and vice versa)

    @override_settings(OVERRIDE_ENDPOINT=dict(core_users_partial_update=True))
    def test_update_attributes_when_put_overwritten(self):
        self.test_original_update_attributes()

    @override_settings(OVERRIDE_ENDPOINT=dict(core_users_update=True))
    def test_patch_attributes_when_put_overwritten(self):
        self.test_original_patch_attributes()
