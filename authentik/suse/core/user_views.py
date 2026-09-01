"""User API Views"""

from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.models import AnonymousUser
from django.db.utils import IntegrityError
from django.urls import reverse_lazy
from django.utils.http import urlencode
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
)
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from structlog.stdlib import get_logger

from authentik.api.validation import validate
from authentik.brands.models import Brand
from authentik.core.api.users import UserPasswordSetSerializer
from authentik.core.api.users import UserViewSet as BaseUserViewSet
from authentik.core.api.utils import (
    LinkSerializer,
)
from authentik.core.middleware import (
    SESSION_KEY_IMPERSONATE_USER,
)
from authentik.core.models import (
    Token,
    User,
)
from authentik.flows.exceptions import FlowNonApplicableException
from authentik.flows.models import FlowToken
from authentik.flows.planner import PLAN_CONTEXT_PENDING_USER, FlowPlanner
from authentik.flows.views.executor import QS_KEY_TOKEN
from authentik.rbac.decorators import permission_required
from authentik.stages.email.flow import pickle_flow_token_for_email

LOGGER = get_logger()


def first(iter):
    try:
        return iter[0]
    except KeyError:
        return None


class UserViewSet(BaseUserViewSet):
    def _create_recovery_link(self, for_email=False, user=None) -> tuple[str, Token]:
        # Same source as authentik/core/api/users#UserViewSet._create_recovery_link
        # but user can be passed to skip the get_object() call

        brand: Brand = self.request._request.brand
        # Check that there is a recovery flow, if not return an error
        flow = brand.flow_recovery
        if not flow:
            raise ValidationError({"non_field_errors": "No recovery flow set."})

        if not user:
            user: User = self.get_object()

        planner = FlowPlanner(flow)
        planner.allow_empty_flows = True
        self.request._request.user = AnonymousUser()
        try:
            plan = planner.plan(
                self.request._request,
                {
                    PLAN_CONTEXT_PENDING_USER: user,
                },
            )
        except FlowNonApplicableException:
            raise ValidationError(
                {"non_field_errors": "Recovery flow not applicable to user"}
            ) from None
        _plan = FlowToken.pickle(plan)
        if for_email:
            _plan = pickle_flow_token_for_email(plan)
        token, __ = FlowToken.objects.update_or_create(
            identifier=f"{user.uid}-password-reset",
            defaults={
                "user": user,
                "flow": flow,
                "_plan": _plan,
                "revoke_on_execution": not for_email,
            },
        )
        querystring = urlencode({QS_KEY_TOKEN: token.key})
        link = self.request.build_absolute_uri(
            reverse_lazy("authentik_core:if-flow", kwargs={"flow_slug": flow.slug})
            + f"?{querystring}"
        )
        return link, token

    # Enforce that the current user can view the target user, as well as reset
    # the target user's password in order to allow creating the link
    def suse_recovery(self, request: Request, pk: int) -> Response:
        user = first(User.objects.filter(pk=pk)[:1])
        if not user:
            raise NotFound()

        required_perms = ["authentik_core.view_user", "authentik_core.reset_user_password"]

        if not self.request.user.has_perms(required_perms, user):
            raise PermissionDenied()

        link, _ = self._create_recovery_link(user=user)
        return Response({"link": link})

    @permission_required("authentik_core.reset_user_password")
    @extend_schema(
        responses={
            "200": LinkSerializer(many=False),
        },
        request=None,
    )
    @action(detail=True, pagination_class=None, filter_backends=[], methods=["POST"])
    def recovery(self, request: Request, pk: int) -> Response:
        """Create a temporary link that a user can use to recover their account"""
        if not settings.OVERRIDE_ENDPOINT.get("core_users_recovery_create"):
            return super().recovery(request, pk)

        return self.suse_recovery(request, pk)

    # Enforce an extra permission, stating that the current user can modify the
    # target user in order to allow password change.
    # other than that, is the same logic as the upstream handler.
    def suse_set_password(
        self, request: Request, pk: int, body: UserPasswordSetSerializer
    ) -> Response:
        user = first(User.objects.filter(pk=pk)[:1])
        if not user:
            raise NotFound()

        required_perms = [
            "authentik_core.view_user",
            "authentik_core.reset_user_password",
            "authentik_core.change_user",
        ]

        if not self.request.user.has_perms(required_perms, user):
            raise PermissionDenied()

        try:
            user.set_password(body.validated_data["password"], request=request)
            user.save()
        except (ValidationError, IntegrityError) as exc:
            LOGGER.debug("Failed to set password", exc=exc)
            return Response(status=400)
        if user.pk == request.user.pk and SESSION_KEY_IMPERSONATE_USER not in self.request.session:
            LOGGER.debug("Updating session hash after password change")
            update_session_auth_hash(self.request, user)
        return Response(status=204)

    @permission_required("authentik_core.reset_user_password")
    @extend_schema(
        request=UserPasswordSetSerializer,
        responses={
            204: OpenApiResponse(description="Successfully changed password"),
            400: OpenApiResponse(description="Bad request"),
        },
    )
    @action(
        detail=True,
        methods=["POST"],
        permission_classes=[IsAuthenticated],
    )
    @validate(UserPasswordSetSerializer)
    def set_password(self, request: Request, pk: int, body: UserPasswordSetSerializer) -> Response:
        if not settings.OVERRIDE_ENDPOINT.get("core_users_set_password_create"):
            return super().set_password(request, pk)
        return self.suse_set_password(request, pk, body)
