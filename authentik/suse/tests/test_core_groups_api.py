"""Test Core Group API"""

from django.db.models import Q
from django.test.utils import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from authentik.core.models import Group, User
from authentik.core.tests.utils import (
    create_test_admin_user,
    create_test_user,
)
from authentik.tenants.utils import get_current_tenant


class TestCoreGroupsListAPI(APITestCase):
    """Test group list new behaviors"""

    def setUp(self) -> None:
        # Gravatar will spawn 3 requests per user:
        # - one for cache key exists
        # - one for cache key expire
        # - one insert on confluct update for the actual value...
        tenant = get_current_tenant()
        tenant.avatars = "none"
        tenant.save()

        self.admin = create_test_admin_user()
        self.user_one = create_test_user()
        self.user_two = create_test_user()

        # Speed up seeding the initial state with bulk_create. from 30s down to ~8s
        Group.objects.bulk_create(
            [Group(name=f"group-{chunk}-{i}") for i in range(5) for chunk in ("one", "two", "both")]
        )

        parents_cls = Group().parents.through
        parents_cls.objects.bulk_create(
            [
                parents_cls(parent_id=parent_id, child_id=child_id)
                for child_id in Group.objects.filter(
                    Q(name__startswith="group-one-") | Q(name__startswith="group-two-")
                ).values_list("pk", flat=True)
                for parent_id in Group.objects.filter(name__startswith="group-both-").values_list(
                    "pk", flat=True
                )
            ]
        )

        membership_cls = self.user_one.ak_groups.through

        membership_cls.objects.bulk_create(
            [
                *[
                    membership_cls(user=self.user_one, group_id=g)
                    for g in Group.objects.filter(name__startswith="group-one-").values_list(
                        "pk", flat=True
                    )
                ],
                *[
                    membership_cls(user=self.user_two, group_id=g)
                    for g in Group.objects.filter(name__startswith="group-two-").values_list(
                        "pk", flat=True
                    )
                ],
                *[
                    membership_cls(user=user, group_id=g)
                    for user in (self.user_one, self.user_two)
                    for g in Group.objects.filter(name__startswith="group-both-").values_list(
                        "pk", flat=True
                    )
                ],
            ]
        )

        User.objects.bulk_create(
            [
                User(
                    name=f"user-{i}",
                    username=f"user-{i}",
                    email=f"user-{i}@goauthentik.io",
                )
                for i in range(30)
            ]
        )

        Group.objects.bulk_create([Group(name=f"group-unrelated-{i}") for i in range(20)])

    # Upstream behavior
    def test_original_list_group(self):
        self.client.force_login(self.admin)

        with self.assertNumQueries(56):
            response = self.client.get(reverse("authentik_api:group-list"))
            self.assertEqual(response.status_code, 200)

        with self.assertNumQueries(88):
            response = self.client.get(
                reverse("authentik_api:group-list", query=dict(page_size=100))
            )
            self.assertEqual(response.status_code, 200)

    # New behavior: omit group expansion
    @override_settings(OVERRIDE_ENDPOINT=dict(core_groups_list=True))
    def test_new_list_group(self):
        self.client.force_login(self.admin)

        with self.assertNumQueries(18):
            response = self.client.get(
                reverse("authentik_api:group-list"),
                headers={
                    "X-SUSE-API-Group-Expand-User-Objects": "false",
                    "X-SUSE-API-Group-Expand-Role-Objects": "false",
                    "X-SUSE-API-Group-Expand-Parent-Objects": "false",
                    "X-SUSE-API-Group-Expand-Child-Objects": "false",
                },
            )
            self.assertEqual(response.status_code, 200)

        with self.assertNumQueries(18):
            response = self.client.get(
                reverse("authentik_api:group-list", query=dict(page_size=100)),
                headers={
                    "X-SUSE-API-Group-Expand-User-Objects": "false",
                    "X-SUSE-API-Group-Expand-Role-Objects": "false",
                    "X-SUSE-API-Group-Expand-Parent-Objects": "false",
                    "X-SUSE-API-Group-Expand-Child-Objects": "false",
                },
            )
            self.assertEqual(response.status_code, 200)
            first_record = response.json()["results"][0]

            # make sure we respect the expected response shape
            users = first_record.get("users")
            assert type(users) is list, '"users" is not a list'

            parents = first_record.get("parents")
            assert type(parents) is list, '"parents" is not a list'

            children = first_record.get("children")
            assert type(children) is list, '"children" is not a list'

            users_obj = first_record.get("users_obj")
            assert type(users_obj) is list, '"users_obj" is not a list'

            parents_obj = first_record.get("parents_obj")
            assert type(parents_obj) is list, '"parents_obj" is not a list'

            children_obj = first_record.get("children_obj")
            assert type(children_obj) is list, '"children_obj" is not a list'
