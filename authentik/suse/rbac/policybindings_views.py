from django.conf import settings
from rest_framework.fields import SerializerMethodField
from rest_framework.serializers import PrimaryKeyRelatedField

from authentik.policies.api.bindings import PolicyBindingSerializer as BasePolicyBindingSerializer
from authentik.policies.api.bindings import PolicyBindingViewSet as BasePolicyBindingViewSet

# from authentik.policies.api.bindings import PolicyBindingModelForeignKey
from authentik.policies.models import PolicyBinding, PolicyBindingModel


class PolicyBindingSerializer(BasePolicyBindingSerializer):
    def _empty_obj(self, instance):
        return {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not settings.OVERRIDE_ENDPOINT.get("policies_bindings_list"):
            return

        request = self.context.get("request")
        if not request:
            return

        # The PolicyBindingModelForeignKey seems like a relic from the past.
        # .select_subclasses materializes the target class "just fine" (so far),
        #
        # This serializer field is _only_ needed for POST/PUT/PATCH request
        # validation for PBM models that define their own:
        # `supported_policy_binding_targets`
        #
        # At the moment that's only the ApplicationEntitlement model class.

        self.fields["target"] = PrimaryKeyRelatedField(
            queryset=PolicyBindingModel.objects.select_subclasses(),
            required=True,
        )

    class Meta:
        model = PolicyBinding
        fields = [
            "pk",
            "policy",
            "group",
            "user",
            "policy_obj",
            "group_obj",
            "user_obj",
            "target",
            "negate",
            "enabled",
            "order",
            "timeout",
            "failure_result",
        ]


class PolicyBindingViewSet(BasePolicyBindingViewSet):
    """PolicyBinding Viewset"""

    # TODO: drop related selects when headers are not present
    queryset = PolicyBinding.objects.all().select_related("target", "group", "user")
    serializer_class = PolicyBindingSerializer
