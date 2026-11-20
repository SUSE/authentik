"""Group API Views"""

from django.conf import settings
from rest_framework.fields import SerializerMethodField
from rest_framework.relations import PrimaryKeyRelatedField
from structlog.stdlib import get_logger

from authentik.core.api.groups import GroupSerializer as BaseGroupSerializer
from authentik.core.api.groups import GroupViewSet as BaseGroupViewSet
from authentik.core.models import Group

LOGGER = get_logger()


class GroupSerializer(BaseGroupSerializer):
    parents = PrimaryKeyRelatedField(
        queryset=Group.objects.all().values_list("pk"),
        many=True,
        required=False,
        allow_empty=True,
        default=list,
    )

    children = PrimaryKeyRelatedField(
        queryset=Group.objects.all().values_list("pk"),
        many=True,
        required=False,
        allow_empty=True,
        default=list,
    )

    def _empty_list(self, _):
        return []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not settings.OVERRIDE_ENDPOINT.get("core_groups_list"):
            return

        request = self.context.get("request")
        if not request:
            return

        if request.headers.get("X-SUSE-API-Group-Expand-User-Objects") == "false":
            self.fields["users_obj"] = SerializerMethodField(method_name="_empty_list")

        if request.headers.get("X-SUSE-API-Group-Expand-Role-Objects") == "false":
            self.fields["roles_obj"] = SerializerMethodField(method_name="_empty_list")
            self.fields["inherited_roles_obj"] = SerializerMethodField(method_name="_empty_list")

        if request.headers.get("X-SUSE-API-Group-Expand-Parent-Objects") == "false":
            self.fields["parents_obj"] = SerializerMethodField(method_name="_empty_list")

        # Children
        if request.headers.get("X-SUSE-API-Group-Expand-Child-Objects") == "false":
            self.fields["children_obj"] = SerializerMethodField(method_name="_empty_list")


class GroupViewSet(BaseGroupViewSet):
    serializer_class = GroupSerializer

    # These are optimized by DRF to
    def get_queryset(self):
        base_qs = super().get_queryset()

        if not settings.OVERRIDE_ENDPOINT.get("core_groups_list"):
            return base_qs

        # prefetch parents & children, they're always rendered as they're in the
        # serializer
        return base_qs.prefetch_related("children").prefetch_related("parents")
