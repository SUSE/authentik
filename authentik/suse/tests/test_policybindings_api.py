from django.test.utils import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from authentik.core.models import Application, Group, User
from authentik.core.tests.utils import create_test_admin_user
from authentik.lib.generators import generate_id
from authentik.policies.models import PolicyBinding


class TestBindingsAPI(APITestCase):
    """Test bindings API"""

    def setUp(self) -> None:
        super().setUp()
        self.admin = create_test_admin_user()
        self.client.force_login(self.admin)

        self.application = Application.objects.create(name=generate_id(), slug=generate_id())

        Group.objects.bulk_create([Group(name=f"group-{i}") for i in range(20)])

        User.objects.bulk_create(
            [
                User(
                    name=f"user-{i}",
                    username=f"user-{i}",
                    email=f"user-{i}@goauthentik.io",
                )
                for i in range(20)
            ]
        )

        PolicyBinding.objects.bulk_create(
            [
                PolicyBinding(target=self.application, group_id=group_id, order=idx)
                for idx, group_id in enumerate(Group.objects.all().values_list("pk", flat=True))
            ]
        )
        PolicyBinding.objects.bulk_create(
            [
                PolicyBinding(target=self.application, user_id=user_id, order=idx)
                for idx, user_id in enumerate(User.objects.all().values_list("pk", flat=True))
            ]
        )

    def _test_upstream_api_bindings_policy(self):
        """Test that API doesn't allow policies to be bound to this"""
        self.client.force_login(self.admin)
        with self.assertNumQueries(34):
            res = self.client.get(reverse("authentik_api:policybinding-list"))
            self.assertEqual(res.status_code, 200)

        with self.assertNumQueries(55):
            res = self.client.get(
                reverse("authentik_api:policybinding-list", query=dict(page_size=100))
            )
            self.assertEqual(res.status_code, 200)

    @override_settings(OVERRIDE_ENDPOINT=dict(policies_bindings_list=True))
    def test_new_behavior_api_bindings_policy(self):
        """Test that API doesn't allow policies to be bound to this"""
        self.client.force_login(self.admin)
        with self.assertNumQueries(14):
            res = self.client.get(reverse("authentik_api:policybinding-list"))
            self.assertEqual(res.status_code, 200)

        with self.assertNumQueries(14):
            res = self.client.get(
                reverse("authentik_api:policybinding-list", query=dict(page_size=100))
            )
            self.assertEqual(res.status_code, 200)
