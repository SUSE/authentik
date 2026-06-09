"""E2E Test SAML RelayState in IdP Initiated Flow"""

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
        self.default_acs_url = "https://mysite.org/acs-consumer/foo-BAR-baz"
        self.provider = SAMLProvider.objects.create(
            authorization_flow=create_test_flow(),
            acs_url=SAMLProvider.SUSE_ACS_URL_SPLIT_NEEDLE.join(
                [
                    self.default_acs_url,
                    "https://mysite.org/acs-consumer/lorem-IPSUM-dolor",
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
                query=dict(RelayState="MyRelayStateHere"),
            )
        )
        self.assertTrue(
            "RelayState=MyRelayStateHere" in response.url,
            "IdP-initiated flow returns the contains the provided RelayState",
        )
