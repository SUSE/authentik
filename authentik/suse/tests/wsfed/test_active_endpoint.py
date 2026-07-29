# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

"""Test Active (SOAP) Authentication flow"""

from django.urls import reverse
from msal.wstrust_request import send_request

from authentik.blueprints.tests import apply_blueprint
from authentik.core.models import Application
from authentik.core.tests.utils import create_test_user
from authentik.flows.models import Flow
from authentik.flows.tests import FlowTestCase
from authentik.lib.generators import generate_id
from authentik.providers.saml.models import SAMLProvider


class TestActiveEndpointCase(FlowTestCase):

    @apply_blueprint("default/flow-default-authentication-flow.yaml")
    def setUp(self) -> None:
        self.flow = Flow.objects.get(slug="default-authentication-flow")

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

    def test_401_empty_request(self):
        response = self.client.post(
            reverse(
                "authentik_providers_saml:wsfed-active",
                kwargs={"application_slug": self.application.slug},
            ),
        )
        self.assertEqual(401, response.status_code)

    def test_401_password_mismatch(self):

        soap_action = "http://docs.oasis-open.org/ws-sx/ws-trust/200512/RST/Issue"
        active_url = reverse(
            "authentik_providers_saml:wsfed-active",
            kwargs={"application_slug": self.provider.application.slug},
        )

        with self.assertRaises(RuntimeError):
            send_request(
                self.user.username,
                "fff",
                active_url,
                active_url,
                soap_action,
                self.client,
                content_type="application/soap+xml",
            )

    def test_200_password_match(self):
        soap_action = "http://docs.oasis-open.org/ws-sx/ws-trust/200512/RST/Issue"
        active_url = reverse(
            "authentik_providers_saml:wsfed-active",
            kwargs={"application_slug": self.provider.application.slug},
        )

        response = send_request(
            self.user.username,
            self.user.username,
            active_url,
            active_url,
            soap_action,
            self.client,
            content_type="application/soap+xml",
        )

        assert "token" in response
        token = response["token"].decode("utf-8")

        # check that the user uid is present in the token
        assert f">{self.user.uid}<" in token
