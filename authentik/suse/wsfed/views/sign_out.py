# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

# Passive auth endpoint
# this is browser-based auth, similar to SAML Post handler
#
# it expects wa=signing1.0 [as-is], wauth=[the auth claim wanted],
# wctx=obscure-token
#
# It outputs an access denied view, or RequestSecurityTokenResponse submitted to
# the ACS URL configured, or to the wreply= qs
# RequestSecurityTokenResponse includes a SAML1.0 Assertion containing the auth
# details


"""authentik SAML IDP Views"""

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import csrf_exempt
from structlog.stdlib import get_logger

from authentik.core.models import Application
from authentik.flows.exceptions import FlowNonApplicableException
from authentik.flows.models import in_memory_stage
from authentik.flows.planner import PLAN_CONTEXT_APPLICATION, PLAN_CONTEXT_SSO, FlowPlanner
from authentik.lib.views import bad_request_message
from authentik.policies.views import BufferedPolicyAccessView
from authentik.providers.saml.models import SAMLProvider
from authentik.stages.consent.stage import (
    PLAN_CONTEXT_CONSENT_HEADER,
    PLAN_CONTEXT_CONSENT_PERMISSIONS,
)
from authentik.suse.wsfed.constants import (
    PLAN_CONTEXT_WS_FED_WA,
    PLAN_CONTEXT_WS_FED_WREPLY,
    WA,
    WS_FED_WA_KEY,
    WS_FED_WREPLY_KEY,
)
from authentik.suse.wsfed.flow import WSTrustSignOutFlowFinalView

LOGGER = get_logger()


@method_decorator(xframe_options_sameorigin, name="dispatch")
@method_decorator(csrf_exempt, name="dispatch")
class WSFedSignOutView(BufferedPolicyAccessView):
    """SAML SSO Base View, which plans a flow and injects our final stage.
    Calls get/post handler."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.plan_context = {}

    def resolve_provider_application(self):
        self.application = get_object_or_404(Application, slug=self.kwargs["application_slug"])
        self.provider: SAMLProvider = get_object_or_404(
            SAMLProvider, pk=self.application.provider_id
        )

    def check_saml_request(self) -> HttpRequest | None:
        try:
            wa = self.request.GET.get(WS_FED_WA_KEY)
            if WA(wa) != WA.SIGN_OUT:
                raise ValueError(f"Unknown WA Value: {wa}")
        except ValueError as e:
            LOGGER.info("unknown wa value", exc=e)
            return bad_request_message(self.request, "Invalid sign-out request.")

        if WS_FED_WREPLY_KEY not in self.request.GET:
            LOGGER.info("wreply is missing")
            return bad_request_message(self.request, "Invalid target")

        self.plan_context[PLAN_CONTEXT_WS_FED_WA] = self.request.GET[WS_FED_WA_KEY]
        self.plan_context[PLAN_CONTEXT_WS_FED_WREPLY] = self.request.GET[WS_FED_WREPLY_KEY]

    def get(self, request: HttpRequest, application_slug: str) -> HttpResponse:
        """Verify the SAML Request, and if valid initiate the FlowPlanner for the application"""
        # Call the method handler, which checks the SAML
        # Request and returns a HTTP Response on error
        method_response = self.check_saml_request()
        if method_response:
            return method_response
        # Regardless, we start the planner and return to it
        planner = FlowPlanner(self.provider.authorization_flow)
        planner.allow_empty_flows = True

        try:
            plan = planner.plan(
                request,
                {
                    PLAN_CONTEXT_SSO: True,
                    PLAN_CONTEXT_APPLICATION: self.application,
                    PLAN_CONTEXT_CONSENT_HEADER: _("You're about to sign into %(application)s.")
                    % {"application": self.application.name},
                    PLAN_CONTEXT_CONSENT_PERMISSIONS: [],
                    **self.plan_context,
                },
            )
        except FlowNonApplicableException:
            raise Http404 from None

        plan.append_stage(in_memory_stage(WSTrustSignOutFlowFinalView))

        return plan.to_redirect(
            request,
            self.provider.authorization_flow,
        )
