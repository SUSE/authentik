# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

from enum import StrEnum


class WA(StrEnum):
    SIGN_IN = "wsignin1.0"
    SIGN_OUT = "wsignout1.0"
    CLEANUP = "wsignoutcleanup1.0"


WS_FED_WCTX_KEY = "wctx"
WS_FED_WAUTH_KEY = "wauth"
WS_FED_WA_KEY = "wa"
WS_FED_WTREALM_KEY = "wtrealm"
WS_FED_WREPLY_KEY = "wreply"

PLAN_CONTEXT_WS_FED = "suse/wsfed"
PLAN_CONTEXT_WS_FED_WCTX = "suse/wsfed/wctx"
PLAN_CONTEXT_WS_FED_WAUTH = "suse/wsfed/wauth"
PLAN_CONTEXT_WS_FED_WA = "suse/wsfed/wa"
PLAN_CONTEXT_WS_FED_WTREALM = "suse/wsfed/wtrealm"
PLAN_CONTEXT_WS_FED_WREPLY = "suse/wsfed/wreply"


# XML XSD References
EC = "http://www.w3.org/2001/10/xml-exc-c14n#"
SE = "http://www.w3.org/2003/05/soap-envelope"
XS = "http://www.w3.org/2001/XMLSchema"
XSI = "http://www.w3.org/2001/XMLSchema-instance"


# Magic SAML strings
SAML1_ASSERTION = "urn:oasis:names:tc:SAML:1.0:assertion"

# Magic SOAP references
MS_STS = "http://schemas.microsoft.com/ws/2008/06/identity/securitytokenservice"
SOAP12 = "http://schemas.xmlsoap.org/wsdl/soap12/"
SP = "http://schemas.xmlsoap.org/ws/2005/07/securitypolicy"

# WS-Trust References
WS_ADDRESSING = "http://www.w3.org/2005/08/addressing"
WS_ADDRESSING_WSDL = "http://www.w3.org/2006/05/addressing/wsdl"
WS_POLICY = "http://schemas.xmlsoap.org/ws/2004/09/policy"
WS_TRUST = "http://docs.oasis-open.org/ws-sx/ws-trust/200512"
WS_UTILITY = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
WSA_ANONNYMOUS = "http://www.w3.org/2005/08/addressing/anonymous"
WSDL = "http://schemas.xmlsoap.org/wsdl/"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"

# Magic WS-Trust strings
WS_TRUST_KEY_TYPE_NO_PROOF = "http://schemas.xmlsoap.org/ws/2005/05/identity/NoProofKey"
WS_TRUST_REQUEST_TYPE_ISSUE = "http://schemas.xmlsoap.org/ws/2005/02/trust/Issue"
WS_TRUST_REQUEST_TYPE_ISSUE_RESULT = (
    "http://docs.oasis-open.org/ws-sx/ws-trust/200512/RSTRC/IssueResult"
)


# from: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-mwbf/77c337e9-e11c-4747-a3cd-ea8faebc9496#Appendix_A_14
class WAuth(StrEnum):
    DEFAULT = "urn:oasis:names:tc:SAML:1.0:am:password"
    BEARER = "urn:oasis:names:tc:SAML:1.0:cm:bearer"

    USERNAME_PASSWORD = (
        "http://schemas.microsoft.com/ws/2008/06/identity/authenticationmethod/password"
    )
    MULTIPLE_AUTHN = "http://schemas.microsoft.com/claims/multipleauthn"
