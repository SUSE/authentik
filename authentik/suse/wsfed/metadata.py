# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

"""
Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
SPDX-License-Identifier: Apache-2.0
"""

from django.http import HttpRequest
from django.urls import reverse
from lxml.etree import Element, SubElement, tostring  # nosec

from authentik.providers.saml.models import SAMLProvider
from authentik.suse.wsfed.constants import (
    MS_STS,
    SOAP12,
    SP,
    WS_ADDRESSING,
    WS_ADDRESSING_WSDL,
    WS_POLICY,
    WS_TRUST,
    WS_UTILITY,
    WSDL,
    XS,
)

NS_MAP = {
    "soap12": SOAP12,
    "sp": SP,
    "tns": MS_STS,  # <-- this one is referred by attribute values
    "wsa10": WS_ADDRESSING,
    "wsaw": WS_ADDRESSING_WSDL,
    "wsdl": WSDL,
    "wsp": WS_POLICY,
    "wsu": WS_UTILITY,
    "xsd": XS,
}


class MetadataProcessor:
    """SAML Identity Provider Metadata Processor"""

    provider: SAMLProvider
    http_request: HttpRequest

    def __init__(self, provider: SAMLProvider, request: HttpRequest):
        self.provider = provider
        self.http_request = request

    def build_entity_descriptor(self) -> str:
        # return self.build_entity_descriptor_xml()
        return tostring(self.build_entity_descriptor_xml()).decode()

    def build_entity_descriptor_xml(self):
        # """Build full EntityDescriptor"""
        active_endpoint = self.http_request.build_absolute_uri(
            reverse(
                "authentik_providers_saml:wsfed-active",
                kwargs={"application_slug": self.provider.application.slug},
            )
        )

        root = Element(
            f"{{{WSDL}}}definitions",
            nsmap=NS_MAP,
            attrib={
                "name": "SecurityTokenService",
                "targetNamespace": "http://schemas.microsoft.com/ws/2008/06/identity/securitytokenservice",
            },
        )

        policy = SubElement(
            root,
            f"{{{WS_POLICY}}}Policy",
            attrib={f"{{{WS_UTILITY}}}Id": "UserNameWSTrustBinding_IWSTrust13Async_Policy"},
        )

        exact_one = SubElement(policy, f"{{{WS_POLICY}}}ExactlyOne")
        all_ = SubElement(exact_one, f"{{{WS_POLICY}}}All")
        transport_binding = SubElement(all_, f"{{{SP}}}TransportBinding")
        tb_policy = SubElement(transport_binding, f"{{{WS_POLICY}}}Policy")

        transport_token = SubElement(tb_policy, f"{{{SP}}}TransportToken")
        tt_policy = SubElement(transport_token, f"{{{WS_POLICY}}}Policy")
        https_token = SubElement(tt_policy, f"{{{SP}}}HttpsToken")
        https_token.attrib["RequireClientCertificate"] = "false"

        algorithm_suite = SubElement(tb_policy, f"{{{SP}}}AlgorithmSuite")
        as_policy = SubElement(algorithm_suite, f"{{{WS_POLICY}}}Policy")
        SubElement(as_policy, f"{{{SP}}}Basic256")

        layout = SubElement(tb_policy, f"{{{SP}}}Layout")
        as_policy = SubElement(layout, f"{{{WS_POLICY}}}Policy")
        SubElement(as_policy, f"{{{SP}}}Strict")
        SubElement(tb_policy, f"{{{SP}}}IncludeTimestamp")

        signed_supporting_tokens = SubElement(all_, f"{{{SP}}}SignedSupportingTokens")
        as_policy = SubElement(signed_supporting_tokens, f"{{{WS_POLICY}}}Policy")
        username_token = SubElement(
            as_policy,
            f"{{{SP}}}UsernameToken",
            attrib={
                f"{{{SP}}}IncludeToken": "http://schemas.xmlsoap.org/ws/2005/07/securitypolicy/IncludeToken/AlwaysToRecipient"
            },
        )

        ut_policy = SubElement(username_token, f"{{{WS_POLICY}}}Policy")
        SubElement(ut_policy, f"{{{SP}}}WssUsernameToken10")
        SubElement(all_, f"{{{WS_ADDRESSING_WSDL}}}UsingAddressing")

        input_message = SubElement(
            root,
            f"{{{WSDL}}}message",
            nsmap=NS_MAP,
            attrib={
                "name": "tns:IWSTrust13Async_Trust13IssueAsync_InputMessage",
            },
        )

        SubElement(
            input_message,
            f"{{{WSDL}}}part",
            nsmap={"q1": WS_TRUST},
            attrib={
                "name": "request",
                "element": "q1:RequestSecurityToken",
            },
        )

        output_message = SubElement(
            root,
            f"{{{WSDL}}}message",
            nsmap=NS_MAP,
            attrib={
                "name": "tns:IWSTrust13Async_Trust13IssueAsync_OutputMessage",
            },
        )
        SubElement(
            output_message,
            f"{{{WSDL}}}part",
            nsmap={"q2": WS_TRUST},
            attrib={
                "name": "response",
                "element": "q2:RequestSecurityTokenResponseCollection",
            },
        )

        port = SubElement(
            root,
            f"{{{WSDL}}}portType",
            nsmap=NS_MAP,
            attrib={
                "name": "IWSTrust13Async",
            },
        )
        port_operation = SubElement(
            port,
            f"{{{WSDL}}}operation",
            nsmap=NS_MAP,
            attrib={
                "name": "Trust13IssueAsync",
            },
        )
        SubElement(
            port_operation,
            f"{{{WSDL}}}input",
            nsmap=NS_MAP,
            attrib={
                "message": "tns:IWSTrust13Async_Trust13IssueAsync_InputMessage",
            },
        )
        SubElement(
            port_operation,
            f"{{{WSDL}}}output",
            nsmap=NS_MAP,
            attrib={
                "message": "tns:IWSTrust13Async_Trust13IssueAsync_OutputMessage",
            },
        )

        wsdl_binding = SubElement(
            root,
            f"{{{WSDL}}}binding",
            nsmap=NS_MAP,
            attrib={
                "name": "UserNameWSTrustBinding_IWSTrust13Async",
                "type": "tns:IWSTrust13Async",
            },
        )

        SubElement(
            wsdl_binding,
            f"{{{WS_POLICY}}}PolicyReference",
            nsmap=NS_MAP,
            attrib={
                "URI": "#UserNameWSTrustBinding_IWSTrust13Async_Policy",
            },
        )

        SubElement(
            wsdl_binding,
            f"{{{SOAP12}}}binding",
            nsmap=NS_MAP,
            attrib={
                "transport": "http://schemas.xmlsoap.org/soap/http",
            },
        )

        binding_operation = SubElement(
            wsdl_binding,
            f"{{{WSDL}}}operation",
            nsmap=NS_MAP,
            attrib={
                "name": "Trust13IssueAsync",
            },
        )
        SubElement(
            binding_operation,
            f"{{{SOAP12}}}operation",
            nsmap=NS_MAP,
            attrib={
                "soapAction": "http://docs.oasis-open.org/ws-sx/ws-trust/200512/RST/Issue",
                "style": "document",
            },
        )

        binding_input = SubElement(binding_operation, f"{{{WSDL}}}input", nsmap=NS_MAP)
        SubElement(binding_input, f"{{{SOAP12}}}body", nsmap=NS_MAP, attrib={"use": "literal"})

        binding_output = SubElement(binding_operation, f"{{{WSDL}}}output", nsmap=NS_MAP)
        SubElement(binding_output, f"{{{SOAP12}}}body", nsmap=NS_MAP, attrib={"use": "literal"})

        wsdl_service = SubElement(
            root,
            f"{{{WSDL}}}service",
            nsmap=NS_MAP,
            attrib={
                "name": "SecurityTokenService",
            },
        )
        wsdl_port = SubElement(
            wsdl_service,
            f"{{{WSDL}}}port",
            nsmap=NS_MAP,
            attrib={
                "binding": "tns:UserNameWSTrustBinding_IWSTrust13Async",
                "name": "UserNameWSTrustBinding_IWSTrust13Async",
            },
        )
        SubElement(
            wsdl_port, f"{{{SOAP12}}}address", nsmap=NS_MAP, attrib={"location": active_endpoint}
        )
        port_er = SubElement(wsdl_port, f"{{{WS_ADDRESSING}}}EndpointReference", nsmap=NS_MAP)
        SubElement(port_er, f"{{{WS_ADDRESSING}}}Address", nsmap=NS_MAP).text = active_endpoint

        return root
