# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

from rest_framework.parsers import BaseParser

from authentik.lib.xml import get_lxml_parser
from authentik.suse.wsfed.constants import (
    SE,
    WS_ADDRESSING,
    WS_POLICY,
    WS_TRUST,
    WS_UTILITY,
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


class SOAPParser(BaseParser):
    """
    SOAP Request parser.
    """

    media_type = "application/soap+xml"

    def parse(self, stream, media_type=None, parser_context=None):
        """
        Return a dictionary with the SOAP Request data.
        """
        blob = stream.read(4_096 * 4)
        parser = get_lxml_parser()
        parser.feed(blob)
        xml = parser.close()
        data = {}

        if action := xml.xpath("//s:Header/wsa:Action", namespaces=NS_MAP):
            data["message_id"] = action[0].text

        if to := xml.xpath("//s:Header/wsa:MessageId", namespaces=NS_MAP):
            data["message_id"] = to[0].text

        if to := xml.xpath("//s:Header/wsa:To", namespaces=NS_MAP):
            data["destination"] = to[0].text

        if user_tag := xml.xpath(
            "//s:Header/wsse:Security/wsse:UsernameToken/wsse:Username", namespaces=NS_MAP
        ):
            data["uid_field"] = user_tag[0].text

        if pw_tag := xml.xpath(
            "//s:Header/wsse:Security/wsse:UsernameToken/wsse:Password", namespaces=NS_MAP
        ):
            data["password"] = pw_tag[0].text

        if request_type := xml.xpath(
            "//s:Body/wst:RequestSecurityToken/wst:RequestType", namespaces=NS_MAP
        ):
            data["request_type"] = request_type[0].text

        if audience := xml.xpath(
            "//s:Body/wst:RequestSecurityToken/wsp:AppliesTo/wsa:EndpointReference/wsa:Address",
            namespaces=NS_MAP,
        ):
            data["audience"] = audience[0].text

        if key_type := xml.xpath(
            "//s:Body/wst:RequestSecurityToken/wst:KeyType", namespaces=NS_MAP
        ):
            data["key_type"] = key_type[0].text

        return data
