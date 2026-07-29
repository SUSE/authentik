# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

"""SAML Assertion generator"""

from lxml import etree  # nosec
from lxml.etree import Element, SubElement  # nosec

from authentik.suse.wsfed.constants import (
    SE,
    WS_ADDRESSING,
    WS_POLICY,
    WS_TRUST,
    WS_TRUST_REQUEST_TYPE_ISSUE_RESULT,
    WS_UTILITY,
    WSA_ANONNYMOUS,
    WSSE,
)

NS_MAP = {
    "s": SE,
    "wsp": WS_POLICY,
    "wsa": WS_ADDRESSING,
    "wsse": WSSE,
    "wst": WS_TRUST,
    "wsu": WS_UTILITY,
}


class SoapEnvelopeProcessor:
    def __init__(self, rstc_processor=None):
        self.rstc_processor = rstc_processor

    def build_response_xml(self):
        envelope = Element(f"{{{SE}}}Envelope", nsmap=NS_MAP)
        header = SubElement(envelope, f"{{{SE}}}Header")

        SubElement(header, f"{{{WS_ADDRESSING}}}Action", {f"{{{SE}}}mustUnderstand": "1"}).text = (
            WS_TRUST_REQUEST_TYPE_ISSUE_RESULT
        )

        SubElement(header, f"{{{WS_ADDRESSING}}}To", {f"{{{SE}}}mustUnderstand": "1"}).text = (
            WSA_ANONNYMOUS
        )

        if self.rstc_processor:
            security = SubElement(header, f"{{{WSSE}}}Security", {f"{{{SE}}}mustUnderstand": "1"})

            timestamp = SubElement(
                security, f"{{{WS_UTILITY}}}Timestamp", {f"{{{WS_UTILITY}}}Id": "_timestamp"}
            )
            SubElement(timestamp, f"{{{WS_UTILITY}}}Created").text = (
                self.rstc_processor.wsfed_processor._issue_instant
            )
            SubElement(timestamp, f"{{{WS_UTILITY}}}Expires").text = (
                self.rstc_processor.wsfed_processor._valid_not_on_or_after
            )

        body = SubElement(envelope, f"{{{SE}}}Body")

        if self.rstc_processor:
            body.append(self.rstc_processor.build_response_xml())
        else:
            fault = SubElement(body, f"{{{SE}}}Fault")
            SubElement(SubElement(fault, f"{{{SE}}}Reason"), f"{{{SE}}}Text").text = "Bad auth"
            SubElement(
                SubElement(SubElement(fault, f"{{{SE}}}Code"), f"{{{SE}}}Subcode"), f"{{{SE}}}Value"
            ).text = "4xx"
        return envelope

    def build_response(self) -> str:
        root_response = self.build_response_xml()
        return etree.tostring(root_response, encoding="UTF-8").decode("utf-8")
