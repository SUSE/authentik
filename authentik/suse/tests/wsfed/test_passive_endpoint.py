# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

"""Test Passive (Web-browser) authentication flow"""

from django.urls import reverse

from authentik.blueprints.tests import apply_blueprint
from authentik.core.models import Application
from authentik.core.tests.utils import create_test_flow, create_test_user
from authentik.flows.models import FlowDesignation
from authentik.flows.tests import FlowTestCase
from authentik.lib.generators import generate_id
from authentik.providers.saml.models import SAMLProvider


class TestPassiveEndpointCase(FlowTestCase):
    """Test ServiceProviderMetadataParser parsing and creation of SAML Provider"""

    # Default flow is needed for the brand to have a default auth flow and
    # the "redirect to login" to apply.
    @apply_blueprint("default/flow-default-authentication-flow.yaml")
    def setUp(self) -> None:
        self.flow = create_test_flow(FlowDesignation.AUTHORIZATION)

        self.provider = SAMLProvider.objects.create(
            name=generate_id(),
            authorization_flow=self.flow,
        )
        self.application = Application.objects.create(
            name=generate_id(),
            slug=generate_id(),
            provider=self.provider,
        )
        self.user = create_test_user()
        self.user.set_password(self.user.username)
        self.user.save()
        self.client.force_login(self.user)

    def test_endpoint_reachable_anon(self):
        self.client.logout()
        response = self.client.get(
            reverse(
                "authentik_providers_saml:wsfed-passive",
                kwargs={"application_slug": self.application.slug},
            ),
        )
        # Redirects to the auth flow
        self.assertEqual(302, response.status_code)

    def test_200_ok_after_redirect(self):
        self.client.logout()
        response = self.client.get(
            reverse(
                "authentik_providers_saml:wsfed-passive",
                kwargs={"application_slug": self.application.slug},
            ),
            follow=True,
        )
        self.assertEqual(200, response.status_code)

    def test_ws_passive_input_validation(self):
        """
        Test partial requests [not containing the minimum the protocol requires
        to process the request]
        """
        qs = {}
        for partial in [None, {"wa": "1"}, {"wctx": "foo"}, {"wtrealm": "foo"}]:
            if partial:
                qs.update(partial)
            response = self.client.get(
                reverse(
                    "authentik_providers_saml:wsfed-passive",
                    kwargs={"application_slug": self.application.slug},
                    query=qs,
                ),
                follow=True,
            )
            self.assertEqual(400, response.status_code)

    def test_ws_passive_wrong_realm(self):
        qs = dict(
            wa="wsignin1.0",
            wctx="foo",
            wtrealm="random string",
        )
        response = self.client.get(
            reverse(
                "authentik_providers_saml:wsfed-passive",
                kwargs={"application_slug": self.application.slug},
                query=qs,
            ),
            follow=True,
        )
        self.assertEqual(400, response.status_code)

    def test_ws_passive_correct_realm(self):
        qs = dict(wa="wsignin1.0", wctx="foo", wtrealm=self.provider.audience, sfe=1)
        # Trigger the state machine first
        self.client.get(
            reverse(
                "authentik_providers_saml:wsfed-passive",
                kwargs={"application_slug": self.application.slug},
                query=qs,
            ),
            follow=True,
        )
        # Since the flow is empty, it'll go through completion and the next
        # stage is the autosubmit
        response = self.client.get(
            reverse("authentik_api:flow-executor", kwargs={"flow_slug": self.flow.slug})
        )

        self.assertEqual(200, response.status_code)
        self.assertStageResponse(response, self.flow, component="ak-stage-autosubmit")
        # The content of the token is unit tested in the
        # request_security_token_response tests.
