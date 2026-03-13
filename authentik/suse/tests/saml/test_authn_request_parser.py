"""Test AuthN Request parser"""

from base64 import b64encode

from django.test import TestCase

from authentik.blueprints.tests import apply_blueprint
from authentik.core.tests.utils import (
    RequestFactory,
    create_test_admin_user,
    create_test_flow,
)
from authentik.providers.saml.exceptions import CannotHandleAssertion
from authentik.providers.saml.models import SAMLPropertyMapping, SAMLProvider
from authentik.providers.saml.processors.assertion import AssertionProcessor
from authentik.providers.saml.processors.authn_request_parser import AuthNRequestParser
from authentik.sources.saml.models import SAMLSource
from authentik.sources.saml.processors.request import RequestProcessor

# Same post request from the original specs
POST_REQUEST = (
    "PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz48c2FtbDJwOkF1dGhuUmVxdWVzdCB4bWxuczpzYW1sMn"
    "A9InVybjpvYXNpczpuYW1lczp0YzpTQU1MOjIuMDpwcm90b2NvbCIgQXNzZXJ0aW9uQ29uc3VtZXJTZXJ2aWNlVVJMPSJo"
    "dHRwczovL2V1LWNlbnRyYWwtMS5zaWduaW4uYXdzLmFtYXpvbi5jb20vcGxhdGZvcm0vc2FtbC9hY3MvMmQ3MzdmOTYtNT"
    "VmYi00MDM1LTk1M2UtNWUyNDEzNGViNzc4IiBEZXN0aW5hdGlvbj0iaHR0cHM6Ly9pZC5iZXJ5anUub3JnL2FwcGxpY2F0"
    "aW9uL3NhbWwvYXdzLXNzby9zc28vYmluZGluZy9wb3N0LyIgSUQ9ImF3c19MRHhMR2V1YnBjNWx4MTJneENnUzZ1UGJpeD"
    "F5ZDVyZSIgSXNzdWVJbnN0YW50PSIyMDIxLTA3LTA2VDE0OjIzOjA2LjM4OFoiIFByb3RvY29sQmluZGluZz0idXJuOm9h"
    "c2lzOm5hbWVzOnRjOlNBTUw6Mi4wOmJpbmRpbmdzOkhUVFAtUE9TVCIgVmVyc2lvbj0iMi4wIj48c2FtbDI6SXNzdWVyIH"
    "htbG5zOnNhbWwyPSJ1cm46b2FzaXM6bmFtZXM6dGM6U0FNTDoyLjA6YXNzZXJ0aW9uIj5odHRwczovL2V1LWNlbnRyYWwt"
    "MS5zaWduaW4uYXdzLmFtYXpvbi5jb20vcGxhdGZvcm0vc2FtbC9kLTk5NjcyZjgyNzg8L3NhbWwyOklzc3Vlcj48c2FtbD"
    "JwOk5hbWVJRFBvbGljeSBGb3JtYXQ9InVybjpvYXNpczpuYW1lczp0YzpTQU1MOjEuMTpuYW1laWQtZm9ybWF0OmVtYWls"
    "QWRkcmVzcyIvPjwvc2FtbDJwOkF1dGhuUmVxdWVzdD4="
)


class TestSUSEAuthNRequestParser(TestCase):
    """Test AuthN Request generator and parser"""

    @apply_blueprint("system/providers-saml.yaml")
    def setUp(self):
        # Stripped certificate validation, we're interested in the ACS
        # validation behavior
        self.request_factory = RequestFactory()
        self.provider: SAMLProvider = SAMLProvider.objects.create(
            authorization_flow=create_test_flow(),
            acs_url="https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/2d737f96-55fb-4035-953e-5e24134eb778",
        )
        self.source = SAMLSource.objects.create(
            slug="provider",
            issuer="authentik",
            pre_authentication_flow=create_test_flow(),
        )
        self.provider.property_mappings.set(SAMLPropertyMapping.objects.all())
        self.provider.save()

    def test_single_acs_url_matching(self):
        """Test SAML request matching a provider with a single ACS URL"""
        request = AuthNRequestParser(self.provider).parse(POST_REQUEST)
        self.assertEqual(
            request.acs_url,
            "https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/2d737f96-55fb-4035-953e-5e24134eb778",
        )

    def test_multiple_acs_url_matching(self):
        """Test SAML request matching a provider with a multiple ACS URL"""
        acs_urls = SAMLProvider.SUSE_ACS_URL_SPLIT_NEEDLE.join(
            [
                # the default
                "https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/foo-bar-baz",
                # vvv the real one from the original testcase
                "https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/2d737f96-55fb-4035-953e-5e24134eb778",
            ]
        )
        self.provider.acs_url = acs_urls
        self.provider.save()

        request = AuthNRequestParser(self.provider).parse(POST_REQUEST)
        self.assertEqual(
            request.acs_url,
            "https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/2d737f96-55fb-4035-953e-5e24134eb778",
        )

    def test_single_acs_url_not_matching(self):
        """Test SAML request not matching the provider's ACS URL"""
        self.provider.acs_url = (
            "https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/foo-bar-baz"
        )
        self.provider.save()

        with self.assertRaises(CannotHandleAssertion):
            AuthNRequestParser(self.provider).parse(POST_REQUEST)

    def test_multiple_acs_url_not_matching(self):
        """Test SAML request not matching any of provider's ACS URL's"""
        acs_urls = SAMLProvider.SUSE_ACS_URL_SPLIT_NEEDLE.join(
            [
                # the default
                "https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/foo-bar-baz",
                # vvv the real one from the original testcase
                "https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/quux-fizz",
            ]
        )
        self.provider.acs_url = acs_urls
        self.provider.save()

        with self.assertRaises(CannotHandleAssertion):
            AuthNRequestParser(self.provider).parse(POST_REQUEST)

    def test_idp_initiated(self):
        """Test IDP-initiated login"""
        default_acs_url = "https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/foo-bar-baz"
        acs_urls = SAMLProvider.SUSE_ACS_URL_SPLIT_NEEDLE.join(
            [
                # the default
                default_acs_url,
                # vvv the real one from the original testcase
                "https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/quux-fizz",
            ]
        )
        self.provider.acs_url = acs_urls
        self.provider.save()

        request = AuthNRequestParser(self.provider).idp_initiated()
        self.assertEqual(request.acs_url, default_acs_url)
        self.assertEqual(request.acs_url, self.provider.suse_default_acs_url)

    def test_recipient_matches_requested_acs(self):
        acs_urls = SAMLProvider.SUSE_ACS_URL_SPLIT_NEEDLE.join(
            [
                "http://testserver/source/saml/provider/acs/",
                # the default
                "https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/foo-bar-baz",
                # vvv the real one from the original testcase
                "https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/quux-fizz",
            ]
        )
        self.provider.acs_url = acs_urls
        self.provider.save()

        user = create_test_admin_user()
        http_request = self.request_factory.get("/", user=user)

        # First create an AuthNRequest
        request_proc = RequestProcessor(self.source, http_request, "")
        request = request_proc.build_auth_n()
        # Now we check the ID and signature
        parsed_auth_n_request = AuthNRequestParser(self.provider).parse(
            b64encode(request.encode()).decode(), ""
        )
        self.assertEqual(parsed_auth_n_request.id, request_proc.request_id)
        self.assertEqual(
            parsed_auth_n_request.acs_url, "http://testserver/source/saml/provider/acs/"
        )

        # Now create a response and convert it to string (provider)
        saml_response_proc = AssertionProcessor(self.provider, http_request, parsed_auth_n_request)
        saml_response_xml = saml_response_proc.get_response()

        self.assertEqual(parsed_auth_n_request.acs_url, saml_response_xml.attrib["Destination"])
        subject_destination = saml_response_xml.xpath(
            "//*[local-name() = 'SubjectConfirmationData']"
        )[0].attrib["Recipient"]
        self.assertEqual(parsed_auth_n_request.acs_url, subject_destination)
