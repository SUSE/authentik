"""Test RolePermissionViewSet api"""

from django.test.utils import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from authentik.api.pagination import SmallerPagination
from authentik.core.models import Group
from authentik.core.tests.utils import create_test_admin_user, create_test_user
from authentik.lib.generators import generate_id
from authentik.rbac.models import Role
from authentik.stages.invitation.models import Invitation
from authentik.tenants.models import Tenant


class TestRBACPermissionRoles(APITestCase):
    """Test RolePermissionViewSet api"""

    def setUp(self) -> None:
        self.superuser = create_test_admin_user()

        self.user = create_test_user()
        self.role = Role.objects.create(name=generate_id())
        self.group = Group.objects.create(name=generate_id())
        self.group.roles.add(self.role)
        self.group.users.add(self.user)

        self.client.force_login(self.superuser)
        inv = Invitation.objects.create(
            name=generate_id(),
            created_by=self.superuser,
        )
        self.role.assign_perms("authentik_stages_invitation.view_invitation", obj=inv)

    def test_original_list(self):
        with self.assertNumQueries(16):
            res = self.client.get(reverse("authentik_api:permissions-roles-list"))
            self.assertEqual(res.status_code, 200)

        for _ in range(1, 40):
            inv = Invitation.objects.create(
                name=generate_id(),
                created_by=self.superuser,
            )
            self.role.assign_perms("authentik_stages_invitation.view_invitation", obj=inv)

        with self.assertNumQueries(54):
            res = self.client.get(reverse("authentik_api:permissions-roles-list"))
            self.assertEqual(res.status_code, 200)
            returned_results = len(res.json()["results"])
            assert (
                returned_results == Tenant.pagination_default_page_size.field.default
            ), "Did not obey old pagination"

        # when page_size is provided... it clamps against max... but when not...
        # max is not taken into account...
        with self.assertNumQueries(34):
            res = self.client.get(
                reverse("authentik_api:permissions-roles-list", query=dict(page_size=20))
            )
            self.assertEqual(res.status_code, 200)
            returned_results = len(res.json()["results"])
            assert (
                returned_results == SmallerPagination.max_page_size
            ), "Did not obey old pagination"

    @override_settings(OVERRIDE_ENDPOINT=dict(rbac_permissions_roles_list=True))
    def test_improved_list(self):
        with self.assertNumQueries(14):
            res = self.client.get(
                reverse("authentik_api:permissions-roles-list", query=dict(suse_serializer="yes"))
            )
            self.assertEqual(res.status_code, 200)

    @override_settings(OVERRIDE_ENDPOINT=dict(rbac_permissions_roles_list=True))
    def test_improved_list_regular_pagination(self):
        total_invitations = 1
        for _ in range(1, 40):
            inv = Invitation.objects.create(
                name=generate_id(),
                created_by=self.superuser,
            )
            self.role.assign_perms("authentik_stages_invitation.view_invitation", obj=inv)
            total_invitations += 1

        with self.assertNumQueries(14):
            res = self.client.get(
                reverse("authentik_api:permissions-roles-list", query=dict(suse_serializer="yes"))
            )
            self.assertEqual(res.status_code, 200)

            results_count = len(res.json()["results"])
            assert (
                results_count == Tenant.pagination_default_page_size.field.default
            ), "Did not obey new pagination"

        # when page_size is provided... it clamps against tenant max instead.
        with self.assertNumQueries(14):
            res = self.client.get(
                reverse(
                    "authentik_api:permissions-roles-list",
                    query=dict(suse_serializer="yes", page_size=100),
                )
            )
            self.assertEqual(res.status_code, 200)

            results_count = len(res.json()["results"])
            assert results_count == total_invitations, "Did not obey new pagination"
