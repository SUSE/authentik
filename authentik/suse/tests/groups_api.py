"""Test Groups API"""

from django.urls.base import reverse
from rest_framework.test import APITestCase

from authentik.core.models import Group
from authentik.core.tests.utils import create_test_user
from authentik.lib.generators import generate_id


class TestGroupsAPI(APITestCase):
    """Test Groups API"""

    def setUp(self) -> None:
        self.login_user = create_test_user()
        self.user = create_test_user()

    def test_add_user_without_dn(self):
        """Test add_user"""
        group = Group.objects.create(
            name=generate_id(),
            attributes=dict(
                allowed_rdns=[
                    "ou=besonders,dc=foo,dc=corp",
                    "ou=special,dc=foo,dc=corp",
                ]
            ),
        )
        self.login_user.assign_perms_to_managed_role("authentik_core.add_user_to_group", group)
        self.login_user.assign_perms_to_managed_role("authentik_core.view_user")
        self.client.force_login(self.login_user)
        res = self.client.post(
            reverse("authentik_api:group-add-user", kwargs={"pk": group.pk}),
            data={
                "pk": self.user.pk,
            },
        )
        self.assertEqual(res.status_code, 400)
        group.refresh_from_db()
        self.assertEqual(list(group.users.all()), [])

    def test_add_user_part_of_rdns(self):
        """Test add_user"""
        group = Group.objects.create(
            name=generate_id(),
            attributes=dict(
                allowed_rdns=[
                    "ou=besonders,dc=foo,dc=corp",
                    "ou=special,dc=foo,dc=corp",
                ]
            ),
        )
        self.user.attributes["distinguishedName"] = (
            f"cn={self.user.username},ou=special,dc=foo,dc=corp"
        )
        self.user.save()
        self.login_user.assign_perms_to_managed_role("authentik_core.add_user_to_group", group)
        self.login_user.assign_perms_to_managed_role("authentik_core.view_user")
        self.client.force_login(self.login_user)
        res = self.client.post(
            reverse("authentik_api:group-add-user", kwargs={"pk": group.pk}),
            data={
                "pk": self.user.pk,
            },
        )
        self.assertEqual(res.status_code, 204)
        group.refresh_from_db()
        self.assertEqual(list(group.users.all()), [self.user])

    def test_add_user_not_part_of_rdns(self):
        """Test add_user"""
        group = Group.objects.create(
            name=generate_id(),
            attributes=dict(
                allowed_rdns=[
                    "ou=besonders,dc=foo,dc=corp",
                    "ou=special,dc=foo,dc=corp",
                ]
            ),
        )
        self.user.attributes["distinguishedName"] = (
            f"cn={self.user.username},ou=not-special,dc=foo,dc=corp"
        )
        self.user.save()
        self.login_user.assign_perms_to_managed_role("authentik_core.add_user_to_group", group)
        self.login_user.assign_perms_to_managed_role("authentik_core.view_user")
        self.client.force_login(self.login_user)
        res = self.client.post(
            reverse("authentik_api:group-add-user", kwargs={"pk": group.pk}),
            data={
                "pk": self.user.pk,
            },
        )
        self.assertEqual(res.status_code, 400)
        group.refresh_from_db()
        self.assertEqual(list(group.users.all()), [])
