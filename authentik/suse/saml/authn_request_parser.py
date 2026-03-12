from defusedxml import ElementTree
from structlog.stdlib import get_logger

from authentik.providers.saml.exceptions import CannotHandleAssertion
from authentik.providers.saml.processors.authn_request_parser import (
    AuthNRequest,
)
from authentik.providers.saml.processors.authn_request_parser import (
    AuthNRequestParser as BaseAuthNRequestParser,
)
from authentik.sources.saml.processors.constants import (
    NS_SAML_PROTOCOL,
    SAML_NAME_ID_FORMAT_UNSPECIFIED,
)

LOGGER = get_logger()
LOGGER.info("Loaded AuthNRequestParser from SUSE Extras")


# Taken from the original request parser
#
# Added support for splitting a very obscure pattern in the url and use to split
# the value, effectively getting an array out of a string field.
class AuthNRequestParser(BaseAuthNRequestParser):
    ACS_URL_SPLIT_NEEDLE = " ~%~ "

    def provider_acs_urls(self):
        return [
            url.strip().lower() for url in self.provider.acs_url.split(self.ACS_URL_SPLIT_NEEDLE)
        ]

    def default_provider_acs_url(self):
        return self.provider_acs_urls()[0]

    def _parse_xml(self, decoded_xml, relay_state):
        root = ElementTree.fromstring(decoded_xml)

        # http://docs.oasis-open.org/security/saml/v2.0/saml-core-2.0-os.pdf
        # `AssertionConsumerServiceURL` can be omitted, and we should fallback to the
        # default ACS URL
        if "AssertionConsumerServiceURL" not in root.attrib:
            request_acs_url = self.default_provider_acs_url()
        else:
            request_acs_url = root.attrib["AssertionConsumerServiceURL"]

        if request_acs_url.lower() not in self.provider_acs_urls():
            msg = (
                f"ACS URL of {request_acs_url} doesn't match Provider "
                f"ACS URL of {','.join(self.provider_acs_urls())}."
            )
            self.logger.warning(msg)
            raise CannotHandleAssertion(msg)

        auth_n_request = AuthNRequest(id=root.attrib["ID"], relay_state=relay_state)

        # Check if AuthnRequest has a NameID Policy object
        name_id_policies = root.findall(f"{{{NS_SAML_PROTOCOL}}}NameIDPolicy")
        if len(name_id_policies) > 0:
            name_id_policy = name_id_policies[0]
            auth_n_request.name_id_policy = name_id_policy.attrib.get(
                "Format",
                SAML_NAME_ID_FORMAT_UNSPECIFIED,
            )

        return auth_n_request
