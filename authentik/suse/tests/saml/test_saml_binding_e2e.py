"""E2E Test SAML Bindings for multi URL ACS"""

from base64 import b64decode

from defusedxml.lxml import fromstring
from django.urls import reverse
from rest_framework.test import APITestCase

from authentik.blueprints.tests import apply_blueprint
from authentik.core.models import Application
from authentik.core.tests.utils import (
    RequestFactory,
    create_test_admin_user,
    create_test_flow,
)
from authentik.lib.generators import generate_id
from authentik.providers.saml.models import SAMLProvider


class TestSUSEAuthNRequestParser(APITestCase):
    """Test AuthN Request generator and parser"""

    @apply_blueprint("system/providers-saml.yaml")
    def setUp(self):
        # Stripped certificate validation, we're interested in the ACS
        # validation behavior
        self.request_factory = RequestFactory()
        self.provider = SAMLProvider.objects.create(
            authorization_flow=create_test_flow(),
            acs_url=SAMLProvider.SUSE_ACS_URL_SPLIT_NEEDLE.join(
                [
                    "https://mysite.org/acs-consumer/foo-bar-baz",
                    "https://mysite.org/acs-consumer/lorem-ipsum-dolor",
                ]
            ),
        )
        self.user = create_test_admin_user()
        self.client.force_login(self.user)
        self.application = Application.objects.create(
            name=generate_id(),
            slug=generate_id(),
            provider=self.provider,
        )

    def test_sso_init_default_acs_redirect(self):
        response = self.client.get(
            reverse(
                "authentik_providers_saml:sso-init",
                kwargs={"application_slug": self.application.slug},
            )
        )
        self.assertTrue(
            response.url.startswith(f"{self.provider.suse_default_acs_url}?SAMLResponse="),
            "IdP-initiated flow returns the first ACS URL",
        )

    def test_sso_init_default_acs_post(self):
        self.provider.sp_binding = "post"
        self.provider.save()

        self.client.get(
            reverse(
                "authentik_providers_saml:sso-init",
                kwargs={"application_slug": self.application.slug},
            ),
            follow=True,
        )
        response = self.client.get(
            reverse(
                "authentik_api:flow-executor",
                kwargs={"flow_slug": self.provider.authorization_flow.slug},
            )
        )

        expected_acs_url = self.provider.suse_default_acs_url
        target_url = response.json()["url"]
        self.assertEqual(
            target_url, expected_acs_url, "IdP-initiated flow: target is the first ACS URL"
        )

        root_xml = fromstring(b64decode(response.json()["attrs"]["SAMLResponse"]))
        self.assertEqual(
            root_xml.attrib["Destination"],
            expected_acs_url,
            "IdP-initiated flow: destination is the first ACS URL",
        )

        subject_xpath = "//*[local-name() = 'SubjectConfirmationData']"
        subject_destination = root_xml.xpath(subject_xpath)[0].attrib["Recipient"]
        self.assertEqual(
            subject_destination,
            expected_acs_url,
            "IdP-initiated flow: recipient is the first ACS URL",
        )
