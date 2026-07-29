# Copyright 2026 - 2026, SUSE LLC <jose.gomez@suse.com>
# SPDX-License-Identifier: Apache-2.0

# WSFed Metadata Exchange (mex) endpoint.
# Outputs a wsdl:definitions pointing to the active endpoint.

"""metadata redirect"""

from django.http import Http404, HttpRequest, HttpResponse
from django.views import View

from authentik.providers.saml.models import SAMLProvider
from authentik.suse.wsfed.metadata import MetadataProcessor


class MetadataDownloadView(View):
    """Redirect to metadata download"""

    def get(self, request: HttpRequest, application_slug: str) -> HttpResponse:
        """Return metadata as XML string"""
        # We don't use self.get_object() on purpose as this view is un-authenticated
        provider = SAMLProvider.objects.filter(application__slug=application_slug).first()
        if not provider:
            raise Http404 from None

        try:
            proc = MetadataProcessor(provider, request)
            metadata = proc.build_entity_descriptor()
            response = HttpResponse(metadata, content_type="text/xml;charset=utf-8")
            return response
        except SAMLProvider.application.RelatedObjectDoesNotExist as e:
            raise Http404 from e
