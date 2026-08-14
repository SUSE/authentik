"""Application API Views"""

from django.conf import settings
from django.shortcuts import get_object_or_404
from guardian.shortcuts import get_objects_for_user
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from structlog.stdlib import get_logger

from authentik.core.api.applications import ApplicationViewSet as BaseAppViewSet
from authentik.core.models import Application, User
from authentik.events.logs import LogEventSerializer, capture_logs
from authentik.policies.api.exec import PolicyTestResultSerializer
from authentik.policies.engine import PolicyEngine
from authentik.policies.types import PolicyResult

LOGGER = get_logger()


class ApplicationViewSet(BaseAppViewSet):

    def _permission_denied(self, message):
        # Endpoint must _always_ return a success, else frontend borks.
        # Yes, 200 OK -> ERROR.
        result = PolicyResult(False)
        result.messages = [message]
        return Response(PolicyTestResultSerializer(result).data)

    @action(detail=True, methods=["GET"])
    def check_access(self, request: Request, slug: str) -> Response:
        """Check access to a single application by slug"""
        if not settings.OVERRIDE_ENDPOINT.get("core_applications_check_access_retrieve"):
            return super().check_access(request, slug)

        # Don't use self.get_object as that checks for view_application permission
        # which the user might not have, even if they have access
        application = get_object_or_404(Application, slug=slug)

        # If the current user is superuser OR can see the admin page & view
        # other users applications, then they can set `for_user`.
        for_user = request.user

        # We can't use here get_objects_for_user for all permissions checks
        # because it does not allow for cross-application permission checks. It
        # complains that autehtnik_rbac & authentik_core are two different
        # apps.
        #
        # As an alternative, we're taking some logic from
        # authentik.core.api.users.py::UserSelfSerializer#get_system_permissions
        # to validate that the current user can see the admin page
        #
        # And then with get_objects_for_user make sure that the current user was
        # granted the permission to check access to other users.
        can_see_admin = (
            "authentik_rbac.access_admin_interface" in request.user.get_all_permissions()
        )

        if "for_user" in request.query_params:
            if not can_see_admin:
                return self._permission_denied("You're not authorized to perform this action")

            for_user_pk = int(request.query_params.get("for_user", 0))
            for_user = (
                get_objects_for_user(
                    request.user,
                    perms=["authentik_core.view_user_applications"],
                    queryset=User.objects.all(),
                )
                .filter(pk=for_user_pk)
                .first()
            )
            if not for_user:
                return self._permission_denied("You're not authorized to perform this action")

        engine = PolicyEngine(application, for_user, request)
        engine.use_cache = False
        with capture_logs() as logs:
            engine.build()
            result = engine.result

        # No idea why the upstream code overwrites the state, but kept it
        # anyways...
        result = PolicyResult(result.passing)
        if request.user.is_superuser:
            log_messages = []
            for log in logs:
                if log.attributes.get("process", "") == "PolicyProcess":
                    continue
                log_messages.append(LogEventSerializer(log).data)
            result.log_messages = log_messages
            response = PolicyTestResultSerializer(result)

        # Allow the users to see in the "response" logs in the UI what happened
        # during policy evaluation.
        #
        # In an ideal world, the log_messages list would be used, but it weirdly
        # does not update upon retries.
        result.messages = [
            '{src}: access check to "{app}" for {dest}: {result}'.format(
                src=request.user.username,
                app=application.name,
                dest=for_user.username,
                result="granted" if result.passing else "denied",
            )
        ]

        response = PolicyTestResultSerializer(result)
        return Response(response.data)
