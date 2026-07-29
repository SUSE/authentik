# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

"""SAML Assertion generator"""

from lxml.etree import Element, tostring  # nosec

from authentik.suse.wsfed.constants import WS_TRUST
from authentik.suse.wsfed.request_security_token_response_processor import NS_MAP


class RequestSecurityTokenResponseCollectionProcessor:
    def __init__(self, wsfed_processor):
        self.wsfed_processor = wsfed_processor

    def build_response_xml(self):
        rstc_response = Element(
            f"{{{WS_TRUST}}}RequestSecurityTokenResponseCollection", nsmap=NS_MAP
        )
        rstc_response.append(self.wsfed_processor.build_response_xml())

        return rstc_response

    def build_response(self) -> str:
        root_response = self.build_response_xml()
        return tostring(root_response, encoding="UTF-8").decode("utf-8")
