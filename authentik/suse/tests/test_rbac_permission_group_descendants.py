"""Test RBAC permissions group descendants"""

from django.test.utils import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from authentik.core.models import Group
from authentik.core.tests.utils import create_test_user
from authentik.lib.generators import generate_id


class TestRBACGroupDescendants(APITestCase):
    """
    Test that granting permissions upon a group, also grant the same
    permissionsto the children groups
    """

    def setUp(self) -> None:
        self.user = create_test_user()

        self.group_admin = Group.objects.create(
            name=f"admin_{generate_id(10)}",
        )
        self.group_admin.users.set([self.user])

        self.target_parent_group = Group.objects.create(
            name=f"parent_{generate_id(10)}",
        )
        self.target_child_group = Group.objects.create(
            name=f"child_{generate_id(10)}",
        )
        self.target_child_group.parents.set([self.target_parent_group])

        self.group_admin.assign_perms_to_managed_role(
            "authentik_core.view_group", obj=self.target_parent_group
        )

    # Baseline

    @override_settings(USE_CUSTOM_GUARDIAN=False)
    def test_original_permission_on_parent(self):
        """Baseline assert: permission granted to the parent, action performed upon parent"""
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "authentik_api:group-detail",
                kwargs={"pk": self.target_parent_group.pk},
            )
        )
        self.assertEqual(response.status_code, 200)

    @override_settings(USE_CUSTOM_GUARDIAN=False)
    def test_original_permission_on_child(self):
        """New behavior: permission granted to the parent, action performed upon child"""
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "authentik_api:group-detail",
                kwargs={"pk": self.target_child_group.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

    # SUSE Behavior

    @override_settings(USE_CUSTOM_GUARDIAN=True)
    def test_permission_on_parent(self):
        """Baseline assert: permission granted to the parent, action performed upon parent"""
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "authentik_api:group-detail",
                kwargs={"pk": self.target_parent_group.pk},
            )
        )
        self.assertEqual(response.status_code, 200)

    @override_settings(USE_CUSTOM_GUARDIAN=True)
    def test_permission_on_child(self):
        """New behavior: permission granted to the parent, action performed upon child"""
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "authentik_api:group-detail",
                kwargs={"pk": self.target_child_group.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
