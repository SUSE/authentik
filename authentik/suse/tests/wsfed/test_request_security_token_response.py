# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

"""Test Service-Provider Metadata Parser"""

from datetime import datetime

from django.test import RequestFactory
from freezegun import freeze_time
from rest_framework.test import APITestCase

from authentik.core.models import Application
from authentik.core.tests.utils import create_test_user
from authentik.lib.generators import generate_id
from authentik.lib.utils.time import timedelta_from_string
from authentik.providers.saml.models import SAMLProvider
from authentik.suse.wsfed.request_security_token_response_processor import (
    NS_MAP,
    RequestSecurityTokenResponseProcessor,
)


class TestRequestSecurityTokenResponse(APITestCase):

    def setUp(self) -> None:
        self.provider = SAMLProvider.objects.create(
            name=generate_id(),
            audience="foo",
        )
        self.application = Application.objects.create(
            name=generate_id(),
            slug=generate_id(),
            provider=self.provider,
        )
        self.user = create_test_user()
        self.factory = RequestFactory()

    def test_consistent_result(self):
        request = self.factory.get("/")
        request.user = self.user
        request.session = self.client.session

        processor = RequestSecurityTokenResponseProcessor(self.provider, request)

        assert processor.build_response() == processor.build_response()

    def test_token_structure(self):
        request = self.factory.get("/")
        request.user = self.user
        request.session = self.client.session

        with freeze_time():
            processor = RequestSecurityTokenResponseProcessor(self.provider, request)
            rstr = processor.build_response_xml()
            rst_tags = rstr.xpath("//wst:RequestedSecurityToken", namespaces=NS_MAP)
            assert len(rst_tags) == 1

            current_time = datetime.utcnow()

            lifetime_created = rstr.find("wst:Lifetime/wsu:Created", namespaces=NS_MAP).text
            lifetime_expires = rstr.find("wst:Lifetime/wsu:Expires", namespaces=NS_MAP).text

            assert lifetime_created == current_time.strftime("%FT%TZ"), "created time mismatch"

            expiry_time = current_time + timedelta_from_string(
                self.provider.assertion_valid_not_on_or_after
            )
            assert lifetime_expires == expiry_time.strftime("%FT%TZ"), "expiry time mismatch"

            assert (
                rstr.find("wsp:AppliesTo/wsa:EndpointReference/wsa:Address", namespaces=NS_MAP).text
                == self.provider.audience
            ), "audience mismatch"

            assert (
                rstr.find("wst:TokenType", namespaces=NS_MAP).text
                == "urn:oasis:names:tc:SAML:1.0:assertion"
            ), "token type mismatch"
            assert (
                rstr.find("wst:RequestType", namespaces=NS_MAP).text
                == "http://schemas.xmlsoap.org/ws/2005/02/trust/Issue"
            ), "issue type mismatch"

    def test_assertion_structure(self):
        request = self.factory.get("/")
        request.user = self.user
        request.session = self.client.session

        with freeze_time():
            processor = RequestSecurityTokenResponseProcessor(self.provider, request)
            rstr = processor.build_response_xml()

            lifetime_created = rstr.find("wst:Lifetime/wsu:Created", namespaces=NS_MAP).text
            lifetime_expires = rstr.find("wst:Lifetime/wsu:Expires", namespaces=NS_MAP).text
            endpoint_address = rstr.find(
                "wsp:AppliesTo/wsa:EndpointReference/wsa:Address", namespaces=NS_MAP
            ).text

            rst = rstr.find("wst:RequestedSecurityToken", namespaces=NS_MAP)

            assertion_instant = rst.find("saml1:Assertion", namespaces=NS_MAP).attrib[
                "IssueInstant"
            ]
            assertion_statement_instant = rst.find(
                "saml1:Assertion/saml1:AuthenticationStatement",
                namespaces=NS_MAP,
            ).attrib["AuthenticationInstant"]
            assert (
                assertion_instant == lifetime_created == assertion_statement_instant
            ), "instant mismatch"

            assertion_not_after = rst.find(
                "saml1:Assertion/saml1:Conditions", namespaces=NS_MAP
            ).attrib["NotOnOrAfter"]
            assert lifetime_expires == assertion_not_after

            assertion_audience = rst.find(
                "saml1:Assertion/saml1:Conditions/saml1:AudienceRestrictionCondition/saml1:Audience",
                namespaces=NS_MAP,
            ).text

            assert endpoint_address == assertion_audience == self.provider.audience
