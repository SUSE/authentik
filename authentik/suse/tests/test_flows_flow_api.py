"""API flow tests"""

from unittest.mock import patch

from django.core.cache import cache
from django.test.utils import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from authentik.core.tests.utils import create_test_admin_user
from authentik.flows.models import Flow, FlowDesignation, FlowStageBinding
from authentik.policies.dummy.models import DummyPolicy
from authentik.policies.models import PolicyBinding
from authentik.stages.dummy.models import DummyStage
from authentik.tenants.models import Tenant


@override_settings(CACHES=dict(default=dict(BACKEND="authentik.suse.memory_cache.MemoryCache")))
class TestFlowsAPI(APITestCase):

    def setUp(self):
        user = create_test_admin_user()
        self.client.force_login(user)

        for i in range(0, 30):
            flow = Flow.objects.create(
                name=f"test-default-context-{i}",
                slug=f"test-default-context-{i}",
                designation=FlowDesignation.AUTHENTICATION,
            )
            false_policy = DummyPolicy.objects.create(
                name=f"dummy2-policy-{i}", result=False, wait_min=1, wait_max=2
            )

            FlowStageBinding.objects.create(
                target=flow, stage=DummyStage.objects.create(name=f"dummy-1-{i}"), order=0
            )
            binding2 = FlowStageBinding.objects.create(
                target=flow,
                stage=DummyStage.objects.create(name=f"dummy-2-{i}"),
                order=1,
                re_evaluate_policies=True,
            )

            PolicyBinding.objects.create(policy=false_policy, target=binding2, order=0)

    @patch.object(cache, "keys")
    def test_upstream_flow_list(self, keys_method_mock):
        page_size = Tenant.pagination_default_page_size.field.default
        with self.assertNumQueries(14):
            response = self.client.get(reverse("authentik_api:flow-list"))
            self.assertEqual(response.status_code, 200)
        assert keys_method_mock.call_count == page_size, "Cache was not checked"

    @patch.object(cache, "keys")
    @override_settings(OVERRIDE_ENDPOINT=dict(flows_instances_list=True))
    def test_improved_flow_list(self, keys_method_mock):
        with self.assertNumQueries(14):
            response = self.client.get(reverse("authentik_api:flow-list"))
            self.assertEqual(response.status_code, 200)
            assert (
                keys_method_mock.call_count == 0
            ), "Cache was checked, even though we disabled it."

        # even when asking more than the default...
        with self.assertNumQueries(14):
            response = self.client.get(
                reverse("authentik_api:flow-list", query=dict(page_size=100))
            )
            self.assertEqual(response.status_code, 200)
            assert (
                keys_method_mock.call_count == 0
            ), "Cache was checked, even though we disabled it."
