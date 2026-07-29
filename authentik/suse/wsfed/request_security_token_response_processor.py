# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

"""SAML Assertion generator"""

from datetime import datetime
from hashlib import sha256
from types import GeneratorType

import xmlsec
from django.http import HttpRequest
from django.utils.timezone import now
from lxml import etree  # nosec
from lxml.etree import Element, SubElement  # nosec
from structlog.stdlib import get_logger

from authentik.core.expression.exceptions import PropertyMappingExpressionException
from authentik.events.models import Event, EventAction
from authentik.events.signals import get_login_event
from authentik.lib.utils.time import timedelta_from_string
from authentik.providers.saml.models import SAMLPropertyMapping, SAMLProvider
from authentik.providers.saml.utils import get_random_id
from authentik.providers.saml.utils.time import get_time_string
from authentik.sources.saml.exceptions import (
    InvalidSignature,
)
from authentik.sources.saml.processors.constants import (
    DIGEST_ALGORITHM_TRANSLATION_MAP,
    NS_SIGNATURE,
    SAML_NAME_ID_FORMAT_UNSPECIFIED,
    SIGN_ALGORITHM_TRANSFORM_MAP,
)
from authentik.suse.wsfed.constants import (
    EC,
    SAML1_ASSERTION,
    WS_ADDRESSING,
    WS_POLICY,
    WS_TRUST,
    WS_TRUST_KEY_TYPE_NO_PROOF,
    WS_TRUST_REQUEST_TYPE_ISSUE,
    WS_UTILITY,
    XS,
    XSI,
    WAuth,
)

LOGGER = get_logger()

NS_MAP = {
    "ec": EC,
    "saml1": SAML1_ASSERTION,
    "wsp": WS_POLICY,
    "wsa": WS_ADDRESSING,
    "wst": WS_TRUST,
    "wsu": WS_UTILITY,
    "xs": XS,
    "xsi": XSI,
    "ds": NS_SIGNATURE,
}


class RequestSecurityTokenResponseProcessor:
    """Generate a SAML Response from an AuthNRequest"""

    provider: SAMLProvider
    http_request: HttpRequest

    _issue_instant: str
    _assertion_id: str
    _response_id: str

    _auth_instant: str
    _valid_not_before: str
    _session_not_on_or_after: str
    _valid_not_on_or_after: str

    session_index: str
    name_id: str
    name_id_format: str
    session_not_on_or_after_datetime: datetime

    def __init__(self, provider: SAMLProvider, request: HttpRequest, wauth=None):
        self.provider = provider
        self.http_request = request
        self.wauth = wauth

        self._issue_instant = get_time_string()
        self._assertion_id = get_random_id()
        self._response_id = get_random_id()

        self._login_event = get_login_event(self.http_request)
        _login_time = now()
        if self._login_event:
            _login_time = self._login_event.created
        self._auth_instant = get_time_string(_login_time)
        self._valid_not_before = get_time_string(
            timedelta_from_string(self.provider.assertion_valid_not_before)
        )
        self.session_not_on_or_after_datetime = now() + timedelta_from_string(
            self.provider.session_valid_not_on_or_after
        )
        self._session_not_on_or_after = get_time_string(self.session_not_on_or_after_datetime)
        self._valid_not_on_or_after = get_time_string(
            timedelta_from_string(self.provider.assertion_valid_not_on_or_after)
        )

    def _make_saml1_attribute(self, name, values, namespace="http://schemas.xmlsoap.org/claims"):
        attribute_element = Element(
            f"{{{SAML1_ASSERTION}}}Attribute",
            {
                "AttributeName": name,
                "AttributeNamespace": namespace,
            },
        )

        for value in values:
            str_value = str(value) if not isinstance(value, str) else value
            SubElement(
                attribute_element,
                f"{{{SAML1_ASSERTION}}}AttributeValue",
                {f"{{{XSI}}}type": "xs:string"},
            ).text = str_value
        return attribute_element

    def get_attributes(self) -> Element:
        """Get AttributeStatement Element with Attributes from Property Mappings."""
        # See the definition in schemas/saml-schema-assertion-1.0.xsd
        attribute_statement = Element(f"{{{SAML1_ASSERTION}}}AttributeStatement")
        attribute_statement.append(self.get_assertion_subject())
        user = self.http_request.user

        # Auth method in the assertion as a fallback
        # https://learn.microsoft.com/en-us/entra/identity/authentication/how-to-mfa-expected-inbound-assertions
        attribute_statement.append(
            self._make_saml1_attribute(
                "authenticationmethod",
                [self.auth_method],
                namespace="http://schemas.microsoft.com/ws/2008/06/identity/claims",
            )
        )

        attribute_statement.append(
            self._make_saml1_attribute(
                "authenticationinstant",
                [self._issue_instant],
                namespace="http://schemas.microsoft.com/ws/2008/06/identity/claims",
            )
        )

        for mapping in SAMLPropertyMapping.objects.filter(provider=self.provider).order_by(
            "saml_name"
        ):
            try:
                mapping: SAMLPropertyMapping
                value = mapping.evaluate(
                    user=user,
                    request=self.http_request,
                    provider=self.provider,
                )
                if value is None:
                    continue

                ns = "http://schemas.xmlsoap.org/claims"
                if mapping.saml_name == "ImmutableID":
                    ns = "http://schemas.microsoft.com/LiveID/Federation/2008/05"
                if not isinstance(value, list | GeneratorType):
                    value = [value]
                attribute_statement.append(self._make_saml1_attribute(mapping.saml_name, value, ns))

            except (PropertyMappingExpressionException, ValueError) as exc:
                # Value error can be raised when assigning invalid data to an attribute
                Event.new(
                    EventAction.CONFIGURATION_ERROR,
                    message=f"Failed to evaluate property-mapping: '{mapping.name}'",
                    provider=self.provider,
                    mapping=mapping,
                ).from_http(self.http_request)
                LOGGER.warning("Failed to evaluate property mapping", exc=exc)
                continue
        return attribute_statement

    def get_assertion_auth_n_statement(self) -> Element:
        """Generate AuthnStatement with AuthnContext and ContextClassRef Elements."""
        auth_n_statement = Element(f"{{{SAML1_ASSERTION}}}AuthenticationStatement")
        auth_n_statement.attrib["AuthenticationInstant"] = self._issue_instant

        # MSoft will ask for the level of authentication
        # https://docs.oasis-open.org/wsfed/federation/v1.2/os/ws-federation-1.2-spec-os.html#_Toc42337312
        self.auth_method = WAuth.DEFAULT
        try:
            self.auth_method = WAuth(self.wauth)
        except ValueError:
            pass

        auth_n_statement.attrib["AuthenticationMethod"] = str(self.auth_method)
        auth_n_statement.append(self.get_assertion_subject())
        self.session_index = sha256(
            self.http_request.session.session_key.encode("ascii")
        ).hexdigest()
        return auth_n_statement

    def get_assertion_conditions(self) -> Element:
        """Generate Conditions with AudienceRestriction and Audience Elements."""
        conditions = Element(f"{{{SAML1_ASSERTION}}}Conditions")
        conditions.attrib["NotBefore"] = self._valid_not_before
        conditions.attrib["NotOnOrAfter"] = self._valid_not_on_or_after
        if self.provider.audience != "":
            audience_restriction = SubElement(
                conditions, f"{{{SAML1_ASSERTION}}}AudienceRestrictionCondition"
            )
            audience = SubElement(audience_restriction, f"{{{SAML1_ASSERTION}}}Audience")
            audience.text = self.provider.audience
        return conditions

    def _evaluate_nameid_mapping(self):
        if self.provider.name_id_mapping:
            try:
                value = self.provider.name_id_mapping.evaluate(
                    user=self.http_request.user,
                    request=self.http_request,
                    provider=self.provider,
                )
                if value is not None:
                    return str(value)
            except PropertyMappingExpressionException as exc:
                Event.new(
                    EventAction.CONFIGURATION_ERROR,
                    message=(
                        "Failed to evaluate property-mapping: "
                        f"'{self.provider.name_id_mapping.name}'",
                    ),
                    provider=self.provider,
                    mapping=self.provider.name_id_mapping,
                ).from_http(self.http_request)
                LOGGER.warning("Failed to evaluate property mapping", exc=exc)

    def get_name_id(self) -> Element:
        """Get NameID Element"""
        self.name_id_format = SAML_NAME_ID_FORMAT_UNSPECIFIED
        self.name_id = self.http_request.user.uid
        if val := self._evaluate_nameid_mapping():
            self.name_id = val

        name_id = Element(
            f"{{{SAML1_ASSERTION}}}NameIdentifier",
            attrib={
                "Format": self.name_id_format,
            },
        )
        name_id.text = self.name_id
        return name_id

    def get_assertion_subject(self) -> Element:
        """Generate Subject Element with NameID and SubjectConfirmation Objects"""
        subject = Element(f"{{{SAML1_ASSERTION}}}Subject")

        subject.append(self.get_name_id())

        subject_confirmation = SubElement(subject, f"{{{SAML1_ASSERTION}}}SubjectConfirmation")
        subject_confirmation_method = SubElement(
            subject_confirmation, f"{{{SAML1_ASSERTION}}}ConfirmationMethod"
        )
        subject_confirmation_method.text = str(WAuth.BEARER)
        return subject

    def get_assertion(self) -> Element:
        """Generate Main Assertion Element"""
        assertion = Element(f"{{{SAML1_ASSERTION}}}Assertion", nsmap=NS_MAP)
        assertion.attrib["AssertionID"] = self._assertion_id
        assertion.attrib["IssueInstant"] = self._issue_instant
        assertion.attrib["Issuer"] = self.provider.issuer
        assertion.attrib["MajorVersion"] = "1"
        assertion.attrib["MinorVersion"] = "1"

        assertion.append(self.get_assertion_conditions())
        assertion.append(self.get_assertion_auth_n_statement())

        assertion.append(self.get_attributes())

        if self.provider.signing_kp and self.provider.sign_assertion:
            sign_algorithm_transform = SIGN_ALGORITHM_TRANSFORM_MAP.get(
                self.provider.signature_algorithm, xmlsec.constants.TransformRsaSha1
            )
            signature = xmlsec.template.create(
                assertion,
                xmlsec.constants.TransformExclC14N,
                sign_algorithm_transform,
                ns=xmlsec.constants.DSigNs,
            )
            assertion.append(signature)
        return assertion

    def get_response(self) -> Element:
        """Generate Root response element"""

        response = Element(f"{{{WS_TRUST}}}RequestSecurityTokenResponse", nsmap=NS_MAP)
        lifetime = SubElement(response, f"{{{WS_TRUST}}}Lifetime", nsmap=NS_MAP)
        created = SubElement(lifetime, f"{{{WS_UTILITY}}}Created", nsmap=NS_MAP)
        created.text = self._issue_instant
        expires = SubElement(lifetime, f"{{{WS_UTILITY}}}Expires", nsmap=NS_MAP)
        expires.text = self._valid_not_on_or_after

        applies_to = SubElement(response, f"{{{WS_POLICY}}}AppliesTo", nsmap=NS_MAP)
        endpoint_reference = SubElement(
            applies_to, f"{{{WS_ADDRESSING}}}EndpointReference", nsmap=NS_MAP
        )
        address = SubElement(endpoint_reference, f"{{{WS_ADDRESSING}}}Address", nsmap=NS_MAP)
        address.text = self.provider.audience

        token_type = SubElement(response, f"{{{WS_TRUST}}}TokenType", nsmap=NS_MAP)
        token_type.text = SAML1_ASSERTION

        request_type = SubElement(response, f"{{{WS_TRUST}}}RequestType", nsmap=NS_MAP)
        request_type.text = WS_TRUST_REQUEST_TYPE_ISSUE

        key_type = SubElement(response, f"{{{WS_TRUST}}}KeyType", nsmap=NS_MAP)
        key_type.text = WS_TRUST_KEY_TYPE_NO_PROOF

        requested_security_token = SubElement(
            response, f"{{{WS_TRUST}}}RequestedSecurityToken", nsmap=NS_MAP
        )
        requested_security_token.append(self.get_assertion())

        return response

    def _sign(self, element: Element):
        """Sign an XML element based on the providers' configured signing settings"""
        digest_algorithm_transform = DIGEST_ALGORITHM_TRANSLATION_MAP.get(
            self.provider.digest_algorithm, xmlsec.constants.TransformSha1
        )
        xmlsec.tree.add_ids(element, ["AssertionID"])
        signature_node = xmlsec.tree.find_node(element, xmlsec.constants.NodeSignature)
        ref = xmlsec.template.add_reference(
            signature_node,
            digest_algorithm_transform,
            uri="#" + element.attrib["AssertionID"],
        )
        xmlsec.template.add_transform(ref, xmlsec.constants.TransformEnveloped)
        xmlsec.template.add_transform(ref, xmlsec.constants.TransformExclC14N)

        key_info = xmlsec.template.ensure_key_info(signature_node)
        xmlsec.template.add_x509_data(key_info)

        ctx = xmlsec.SignatureContext()

        key = xmlsec.Key.from_memory(
            self.provider.signing_kp.key_data,
            xmlsec.constants.KeyDataFormatPem,
            None,
        )
        key.load_cert_from_memory(
            self.provider.signing_kp.certificate_data,
            xmlsec.constants.KeyDataFormatCertPem,
        )
        ctx.key = key
        try:
            ctx.sign(signature_node)
        except xmlsec.Error as exc:
            raise InvalidSignature() from exc

    def build_response_xml(self):
        """Build string XML Response and sign if signing is enabled."""
        root_response = self.get_response()
        if self.provider.signing_kp:
            if self.provider.sign_assertion:
                assertion = root_response.xpath("//saml1:Assertion", namespaces=NS_MAP)[0]
                self._sign(assertion)
        return root_response

    def build_response(self) -> str:
        root_response = self.build_response_xml()
        return etree.tostring(root_response, encoding="UTF-8").decode("utf-8")
