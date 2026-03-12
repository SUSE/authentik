"""Test AuthN Request parser"""

from django.test import TestCase

from authentik.blueprints.tests import apply_blueprint
from authentik.core.tests.utils import (
    RequestFactory,
    create_test_flow,
)
from authentik.providers.saml.exceptions import CannotHandleAssertion
from authentik.providers.saml.models import SAMLPropertyMapping, SAMLProvider
from authentik.suse.saml.authn_request_parser import AuthNRequestParser

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
            acs_url="http://testserver/source/saml/provider/acs/",
        )
        self.provider.property_mappings.set(SAMLPropertyMapping.objects.all())
        self.provider.save()

    def test_single_acs_url_matching(self):
        """Test SAML request matching a provider with a single ACS URL"""
        self.provider.acs_url = "https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/2d737f96-55fb-4035-953e-5e24134eb778"
        self.provider.save()

        AuthNRequestParser(self.provider).parse(POST_REQUEST)

    def test_multiple_acs_url_matching(self):
        """Test SAML request matching a provider with a multiple ACS URL"""
        acs_urls = AuthNRequestParser.ACS_URL_SPLIT_NEEDLE.join(
            [
                # the default
                "https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/foo-bar-baz",
                # vvv the real one from the original testcase
                "https://eu-central-1.signin.aws.amazon.com/platform/saml/acs/2d737f96-55fb-4035-953e-5e24134eb778",
            ]
        )
        self.provider.acs_url = acs_urls
        self.provider.save()

        AuthNRequestParser(self.provider).parse(POST_REQUEST)

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
        acs_urls = AuthNRequestParser.ACS_URL_SPLIT_NEEDLE.join(
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
