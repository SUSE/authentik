# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

# Active auth endpoint
# this is the SOAP call from windows device for authentication
# It outputs any error code, or RequestSecurityTokenResponseCollection
# containing a single RequestSecurityTokenResponse [exactly the same from the
# passive endpoint]

"""authentik SAML IDP Views"""

import io
import json

from django.contrib.auth.signals import user_logged_in
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import csrf_exempt
from structlog.stdlib import get_logger

from authentik.core.models import Application
from authentik.flows.exceptions import EmptyFlowException, FlowNonApplicableException
from authentik.flows.models import FlowDesignation
from authentik.flows.planner import (
    PLAN_CONTEXT_APPLICATION,
    PLAN_CONTEXT_POST,
)
from authentik.flows.views.executor import (
    SESSION_KEY_POST,
    ToDefaultFlow,
)
from authentik.policies.views import BufferedPolicyAccessView
from authentik.providers.saml.models import SAMLProvider
from authentik.suse.wsfed import SOAPParser
from authentik.suse.wsfed.constants import PLAN_CONTEXT_WS_FED
from authentik.suse.wsfed.flow_planner import FlowPlanner
from authentik.suse.wsfed.request_security_token_response_collection_processor import (
    RequestSecurityTokenResponseCollectionProcessor,
)
from authentik.suse.wsfed.request_security_token_response_processor import (
    RequestSecurityTokenResponseProcessor,
)
from authentik.suse.wsfed.soap_envelope_processor import SoapEnvelopeProcessor

LOGGER = get_logger()


@method_decorator(xframe_options_sameorigin, name="dispatch")
@method_decorator(csrf_exempt, name="dispatch")
class WSFedActiveView(BufferedPolicyAccessView):
    """SAML SSO Base View, which plans a flow and injects our final stage.
    Calls get/post handler."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.plan_context = {}

    def get_request_data(self, request):
        if request.content_type != "application/soap+xml":
            return {}
        return SOAPParser().parse(io.BytesIO(self.request.body))

    def resolve_canonical_username_from_application(self, username):
        """
        Return the real username from a UPN provided.

        Windows may have a different UPN domain tied to a username, this UPN is
        provisioned via SCIM and tied to the application via the backchannel
        provider relationship.

        If no backchannel provider is present, then we use the username as-is.
        """
        provider = self.application.backchannel_providers.select_subclasses().first()
        if not provider:
            return username

        username_from_scim = (
            provider.scimprovideruser_set.all()
            .filter(attributes__userPrincipalName=username)
            .values_list("user__username")
            .first()
        )
        if not username_from_scim:
            return username

        return username_from_scim[0]

    def handle_no_permission(self) -> HttpResponse:
        """User has no access and is not authenticated, so we remember the application
        they try to access and redirect to the login URL. The application is saved to show
        a hint on the Identification Stage what the user should login for."""

        # The request body contains the password in plain text... be careful
        LOGGER.info(
            "Incoming SOAP Request",
            method=self.request.method,
            headers=self.request.headers,
        )
        data = self.get_request_data(self.request)

        # Do not process the request if there's no enough data.
        if not (data.get("uid_field") and data.get("password")):
            return self.soap_fail()

        # Resolve the username back to the authentik's username
        if "uid_field" in data:
            data["uid_field"] = self.resolve_canonical_username_from_application(data["uid_field"])

        # Fake the request for the Flow Planner to think it's a JSON Request
        self.request.content_type = "application/json"
        self.request.META["CONTENT_TYPE"] = "application/json"
        self.request._body = json.dumps(data).encode("utf-8")

        # Process the whole flow
        flow_context = {PLAN_CONTEXT_WS_FED: True}
        authn_flow = None
        if self.application:
            flow_context[PLAN_CONTEXT_APPLICATION] = self.application
            if self.provider and self.provider.authentication_flow:
                authn_flow = self.provider.authentication_flow

        # Because this view might get hit with a POST request, we need to preserve that data
        # since later views might need it (mostly SAML)
        if self.request.method == "POST":
            self.request.session[SESSION_KEY_POST] = self.request.POST
            flow_context[PLAN_CONTEXT_POST] = self.request.POST

        if not authn_flow:
            authn_flow = ToDefaultFlow.get_flow(self.request, FlowDesignation.AUTHENTICATION)
            if not authn_flow:
                raise Http404

        planner = FlowPlanner(authn_flow)
        planner.use_cache = False

        self.request.session.save()

        try:
            plan = planner.plan(self.request, self.modify_flow_context(authn_flow, flow_context))
        except (FlowNonApplicableException, EmptyFlowException) as exc:
            LOGGER.warning("Non-applicable authentication flow", exc=exc)
            raise Http404 from None

        redir = plan.run_until_completion(self.request, authn_flow)

        if not redir:
            return self.soap_fail()

        self.request.user = plan.context["pending_user"]
        # The post handler takes care of the rest
        return self.soap_success(self.request, self.provider)

    def resolve_provider_application(self):
        self.application = get_object_or_404(Application, slug=self.kwargs["application_slug"])
        self.provider: SAMLProvider = get_object_or_404(
            SAMLProvider, pk=self.application.provider_id
        )

    def soap_fail(self) -> HttpResponse:
        return HttpResponse(content=SoapEnvelopeProcessor(None).build_response(), status=401)

    def soap_success(self, request: HttpRequest, provider: SAMLProvider) -> HttpResponse:
        rstr_processor = RequestSecurityTokenResponseProcessor(provider, request, "")
        rstcc_processor = RequestSecurityTokenResponseCollectionProcessor(rstr_processor)
        soap_processor = SoapEnvelopeProcessor(rstcc_processor)

        # Not clear yet why the signal is not created after sign-in, but
        # doesn't hurt sending this here
        user_logged_in.send(sender=self.__class__, user=request.user, request=request)
        return HttpResponse(content=soap_processor.build_response())
