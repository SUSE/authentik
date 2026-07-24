# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

"""Test Service-Provider Metadata Parser"""

from django.test import RequestFactory
from django.urls import reverse
from rest_framework.test import APITestCase

from authentik.core.models import Application
from authentik.core.tests.utils import create_test_flow
from authentik.lib.generators import generate_id
from authentik.lib.xml import lxml_from_string
from authentik.providers.saml.models import SAMLProvider
from authentik.suse.wsfed.metadata import NS_MAP


class TestWSFedMex(APITestCase):
    """Test ServiceProviderMetadataParser parsing and creation of SAML Provider"""

    def setUp(self) -> None:
        self.flow = create_test_flow()
        self.factory = RequestFactory()

        self.provider = SAMLProvider.objects.create(
            name=generate_id(),
            authorization_flow=self.flow,
        )
        self.application = Application.objects.create(
            name=generate_id(),
            slug=generate_id(),
            provider=self.provider,
        )

    def test_endpoint_reachable_anon(self):
        response = self.client.get(
            reverse(
                "authentik_providers_saml:wsfed-mex",
                kwargs={"application_slug": self.application.slug},
            ),
        )
        self.assertEqual(200, response.status_code)

    def test_consistent(self):
        """Test that metadata generation is consistent"""
        uri = reverse(
            "authentik_providers_saml:wsfed-mex", kwargs={"application_slug": self.application.slug}
        )
        metadata_a = self.client.get(uri).content
        metadata_b = self.client.get(uri).content
        self.assertEqual(metadata_a, metadata_b)

    def test_service_references(self):
        response = self.client.get(
            reverse(
                "authentik_providers_saml:wsfed-mex",
                kwargs={"application_slug": self.application.slug},
            )
        )
        metadata = lxml_from_string(response.content)

        sts_tags = metadata.xpath("//wsdl:service[@name='SecurityTokenService']", namespaces=NS_MAP)
        self.assertFalse(len(sts_tags) == 0, "wsdl:service for SecurityTokenService is not present")
        self.assertTrue(
            len(sts_tags) == 1,
            (
                "wsdl:service for SecurityTokenService contains more"
                "than one service, adjust the test."
            ),
        )
        sts_tag = sts_tags[0]

        address_tags = sts_tag.xpath("//soap12:address", namespaces=NS_MAP)
        self.assertFalse(len(sts_tags) == 0, "soap12:address for Service is not present")
        self.assertTrue(len(sts_tags) == 1, "too many soap12:address elements")
        address_tag = address_tags[0]

        uri = reverse(
            "authentik_providers_saml:wsfed-active",
            kwargs={"application_slug": self.provider.application.slug},
        )
        # need a valid request to generate an absolute uri from the test context.
        req = self.factory.get("/")
        assert (
            req.build_absolute_uri(uri) == address_tag.attrib["location"]
        ), "active endpoint not matching"
