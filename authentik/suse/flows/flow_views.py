"""Flow API Views"""

from django.conf import settings

from authentik.flows.api.flows import FlowSerializer as BaseFlowSerializer
from authentik.flows.api.flows import FlowSetSerializer as BaseFlowSetSerializer
from authentik.flows.api.flows import FlowViewSet as BaseFlowViewSet


class FlowSerializer(BaseFlowSerializer):
    def get_cache_count(self, flow) -> int:
        # This serializer is also used in the password stage directly, to keep
        # the feature flag DRY, it's moved here instead of in the drf view
        # code.
        if not settings.OVERRIDE_ENDPOINT.get("flows_instances_list"):
            return super().get_cache_count(flow)

        return 0


class FlowSetSerializer(BaseFlowSetSerializer, FlowSerializer):
    pass


class FlowViewSet(BaseFlowViewSet):
    serializer_class = FlowSerializer
