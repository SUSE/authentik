# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

"""authentik SAML IDP Views"""

from django.http import HttpRequest, HttpResponse
from django.http.response import HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from structlog.stdlib import get_logger

from authentik.core.models import Application, AuthenticatedSession
from authentik.events.models import Event, EventAction
from authentik.flows.challenge import (
    PLAN_CONTEXT_TITLE,
    AutosubmitChallenge,
    AutoSubmitChallengeResponse,
    Challenge,
    ChallengeResponse,
)
from authentik.flows.planner import PLAN_CONTEXT_APPLICATION
from authentik.flows.stage import ChallengeStageView
from authentik.policies.utils import delete_none_values
from authentik.providers.saml.models import SAMLProvider, SAMLSession
from authentik.sources.saml.exceptions import SAMLException
from authentik.suse.wsfed.request_security_token_response_processor import (
    RequestSecurityTokenResponseProcessor,
)

LOGGER = get_logger()
# This View doesn't have a URL on purpose, as its called by the FlowExecutor

# This looks less _horrible_ after reordering all the hacks. A lot of the code
# had to be duplicated cuz the upstream controller has the bulk of the logic on
# the main dispatcher (get/post) method.


class WSTrustFlowFinalView(ChallengeStageView):
    """View used by FlowExecutor after all stages have passed. Logs the authorization,
    and redirects to the SP (if REDIRECT is configured) or shows an auto-submit element
    (if POST is configured)."""

    response_class = AutoSubmitChallengeResponse

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        application: Application = self.executor.plan.context[PLAN_CONTEXT_APPLICATION]
        provider: SAMLProvider = get_object_or_404(SAMLProvider, pk=application.provider_id)

        processor = RequestSecurityTokenResponseProcessor(
            provider, request, self.executor.plan.context.get("suse/wsfed/wauth")
        )
        response = processor.build_response()

        try:
            # Create SAMLSession to track this login
            auth_session = AuthenticatedSession.from_request(request, request.user)
            if auth_session:
                # Since samlsessions should only exist uniquely for an active session and a provider
                # any existing combination is likely an old, dead session
                SAMLSession.objects.filter(
                    session_index=processor.session_index, provider=provider
                ).delete()

                SAMLSession.objects.update_or_create(
                    session_index=processor.session_index,
                    provider=provider,
                    defaults={
                        "user": request.user,
                        "session": auth_session,
                        "name_id": processor.name_id,
                        "name_id_format": processor.name_id_format,
                        "expires": processor.session_not_on_or_after_datetime,
                        "expiring": True,
                    },
                )
        except SAMLException as exc:
            Event.new(
                EventAction.CONFIGURATION_ERROR,
                message=f"Failed to process SAML assertion: {str(exc)}",
                provider=provider,
            ).from_http(self.request)
            return self.executor.stage_invalid()

        # Log Application Authorization
        Event.new(
            EventAction.AUTHORIZE_APPLICATION,
            authorized_application=application,
            flow=self.executor.plan.flow_pk,
        ).from_http(self.request)

        form_attrs = delete_none_values(
            {
                "wresult": response,
                "wctx": self.executor.plan.context["suse/wsfed/wctx"],
                "wa": self.executor.plan.context["suse/wsfed/wa"],
            }
        )

        reply_to = self.executor.plan.context.get("suse/wsfed/wreply", provider.acs_url)
        return super().get(
            self.request,
            **{
                "component": "ak-stage-autosubmit",
                "title": self.executor.plan.context.get(
                    PLAN_CONTEXT_TITLE,
                    _("Redirecting to {app}...".format_map({"app": application.name})),
                ),
                "url": reply_to,
                "attrs": form_attrs,
            },
        )

    def get_challenge(self, *args, **kwargs) -> Challenge:
        return AutosubmitChallenge(data=kwargs)

    def challenge_valid(self, response: ChallengeResponse) -> HttpResponse:
        # We'll never get here since the challenge redirects to the SP
        response = self.get(self.request)

        if response:
            return response

        return HttpResponseBadRequest()


class WSTrustSignOutFlowFinalView(ChallengeStageView):
    """View used by FlowExecutor after all stages have passed. Logs the authorization,
    and redirects to the SP (if REDIRECT is configured) or shows an auto-submit element
    (if POST is configured)."""

    response_class = AutoSubmitChallengeResponse

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        application: Application = self.executor.plan.context[PLAN_CONTEXT_APPLICATION]
        provider: SAMLProvider = get_object_or_404(SAMLProvider, pk=application.provider_id)

        form_attrs = delete_none_values(
            {
                "wreply": self.executor.plan.context["suse/wsfed/wreply"],
                "wa": self.executor.plan.context["suse/wsfed/wa"],
            }
        )

        reply_to = self.executor.plan.context.get("suse/wsfed/wreply", provider.acs_url)
        return super().get(
            self.request,
            **{
                "component": "ak-stage-autosubmit",
                "title": self.executor.plan.context.get(
                    PLAN_CONTEXT_TITLE,
                    _("Signing out from {app}...".format_map({"app": application.name})),
                ),
                "url": reply_to,
                "attrs": form_attrs,
            },
        )

    def get_challenge(self, *args, **kwargs) -> Challenge:
        return AutosubmitChallenge(data=kwargs)

    def challenge_valid(self, response: ChallengeResponse) -> HttpResponse:
        # We'll never get here since the challenge redirects to the SP
        response = self.get(self.request)

        if response:
            return response

        return HttpResponseBadRequest()
