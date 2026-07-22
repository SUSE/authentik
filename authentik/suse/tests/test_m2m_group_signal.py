"""
Tests for M2M signal updating the user timestamp
"""

from rest_framework.test import APITestCase

from authentik.core.models import Group
from authentik.core.tests.utils import create_test_user


class TestM2MGroupSignal(APITestCase):
    """Test User Email Validation API based on dynamic configuration"""

    def setUp(self) -> None:
        super().setUp()

        self.user = create_test_user()
        self.user.save()  # bump last_updated
        self.group = Group.objects.create(name=f"test-group-{self.user.name}", is_superuser=True)

    def test_add_user_to_group_way(self):
        before = self.user.last_updated
        self.group.users.add(self.user)
        self.user.refresh_from_db()

        after = self.user.last_updated
        assert before < after, "timestamp did not change"

    def test_add_group_to_user_way(self):
        before = self.user.last_updated
        self.user.ak_groups.add(self.group)
        self.user.refresh_from_db()

        after = self.user.last_updated
        assert before < after, "timestamp did not change"
