"""Application API Views"""

import pglock
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from guardian.shortcuts import get_objects_for_user
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
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




def user_app_lock(user_pk):
    return pglock.advisory(
        lock_id=f"suse.com/app_access/suse/{user_pk}",
        side_effect=pglock.Return,
    )

def user_app_cache_key(user_pk: str) -> str:
    """Cache key where application list for user is saved"""
    return f"suse.com/app_access/suse/{user_pk}"


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


    def _suse_expand_applications(self, pks):
        """
        Re-fetch with proper prefetching for serialization
        """
        if not pks:
            return self.get_queryset().none()
        return (
            self.get_queryset()
            .filter(pk__in=pks)
        )


    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="superuser_full_list",
                location=OpenApiParameter.QUERY,
                type=OpenApiTypes.BOOL,
            ),
            OpenApiParameter(
                name="for_user",
                location=OpenApiParameter.QUERY,
                type=OpenApiTypes.INT,
            ),
            OpenApiParameter(
                name="only_with_launch_url",
                location=OpenApiParameter.QUERY,
                type=OpenApiTypes.BOOL,
            ),
        ]
    )
    def list(self, request: Request) -> Response:
        if not settings.OVERRIDE_ENDPOINT.get("core_applications_list"):
            return super().list(request)

        """Custom application list method that evaluates results on cache always"""
        superuser_full_list = (
            str(request.query_params.get("superuser_full_list", "false")).lower() == "true"
        )

        # Administrative variant, spawned by the admin frontend
        if superuser_full_list:
            if request.user.is_superuser:
                # Super users don't need extra processing. They get the raw app list.
                return super().list(request)
            else:
                # Non superusers (meaning operators and/or app admins)
                # can only see what objects they have assigned
                #
                # The super method _filter_queryset_for_list skips the object
                # permission (guardian) filter, here we do want that permission
                # filter.
                queryset = self.filter_queryset(self.get_queryset())
                paged_apps = self.paginator.paginate_queryset(queryset, request)
                serializer = self.get_serializer(paged_apps, many=True)
                return self.get_paginated_response(serializer.data)

        # Here we're on the user-frontend variant, applications are filtered by
        # what it's bound to the user via PolicyBindingModels
        user = self.request.user

        # if for_user is requested, then find out the effective user we want to inspect
        if "for_user" in request.query_params:
            LOGGER.debug("Verifying for_user param")
            try:
                for_user: int = int(request.query_params.get("for_user", 0))
                for_user = (
                    get_objects_for_user(request.user, "authentik_core.view_user_applications")
                    .filter(pk=for_user)
                    .first()
                )
                if not for_user:
                    raise ValidationError({"for_user": "User not found"})
            except ValueError as exc:
                raise ValidationError from exc

            LOGGER.debug("Changing effective user",
                from_username=user.username, to_username=for_user.username)
            user = for_user

        # Check the cache
        allowed_applications = cache.get(user_app_cache_key(user.pk))

        if allowed_applications is None:
            LOGGER.debug("Computing application list for user", username=user.username)
            queryset = self._filter_queryset_for_list(self.get_queryset())

            # When not cached, compute the app list, we'll use locks to
            # coordinate concurrent requests.
            with user_app_lock(user.pk):
                # Before computing, check the cache again, in case a request
                # came in after our last cache check but before our cache
                # write
                if cached_allowed_apps := cache.get(user_app_cache_key(user.pk)):
                    # if it happened: then avoid computation and use the cache
                    allowed_applications = cached_allowed_apps
                    LOGGER.debug(
                        "Using precomputed allowed applications",
                        application_count=len(allowed_applications)
                    )
                else:
                    LOGGER.debug(
                        "Computing allowed applications", user_pk=user.pk
                    )
                    # else: it's a good time to compute & write the cache for
                    # subsequent requests.
                    allowed_applications = [
                        app.pk
                        for app in self._get_allowed_applications(queryset, user=user)
                    ]
                    cache.set(
                        user_app_cache_key(user.pk),
                        allowed_applications,
                        timeout=settings.SUSE_APPLICATION_LIST_CACHE_TTL
                    )

        LOGGER.debug(
            "Expanding application list [from pk -> object]",
            application_count=len(allowed_applications)
        )
        # expand, apply pagination, and return
        queryset = self._suse_expand_applications(allowed_applications)
        return self._render_queryset(request, queryset)

    def _render_queryset(self, request, queryset):
        only_with_launch_url = str(
            request.query_params.get("only_with_launch_url", "false")
        ).lower()

        if only_with_launch_url == "true":
            # apply launch url filters
            queryset = queryset.exclude(
                Q(meta_launch_url="", provider__isnull=True) | Q(meta_launch_url="blank://blank")
            )
        paged_apps = self.paginator.paginate_queryset(queryset, request)
        serializer = self.get_serializer(paged_apps, many=True)
        return self.get_paginated_response(serializer.data)
