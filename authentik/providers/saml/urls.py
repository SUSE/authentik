"""authentik SAML IDP URLs"""

from django.urls import path

from authentik.providers.saml.api.property_mappings import SAMLPropertyMappingViewSet
from authentik.providers.saml.api.providers import SAMLProviderViewSet
from authentik.providers.saml.views import metadata, sso
from authentik.providers.saml.views.sp_slo import (
    SPInitiatedSLOBindingPOSTView,
    SPInitiatedSLOBindingRedirectView,
)
from authentik.suse.wsfed.views.active import WSFedActiveView
from authentik.suse.wsfed.views.metadata import MetadataDownloadView as WSFedMetadataDownloadView
from authentik.suse.wsfed.views.passive import WSFedPassiveView
from authentik.suse.wsfed.views.sign_out import WSFedSignOutView

urlpatterns = [
    # SSO Bindings
    path(
        "<slug:application_slug>/sso/binding/redirect/",
        sso.SAMLSSOBindingRedirectView.as_view(),
        name="sso-redirect",
    ),
    path(
        "<slug:application_slug>/sso/binding/post/",
        sso.SAMLSSOBindingPOSTView.as_view(),
        name="sso-post",
    ),
    # SSO IdP Initiated
    path(
        "<slug:application_slug>/sso/binding/init/",
        sso.SAMLSSOBindingInitView.as_view(),
        name="sso-init",
    ),
    # SLO Bindings - SP-initiated
    path(
        "<slug:application_slug>/slo/binding/redirect/",
        SPInitiatedSLOBindingRedirectView.as_view(),
        name="slo-redirect",
    ),
    path(
        "<slug:application_slug>/slo/binding/post/",
        SPInitiatedSLOBindingPOSTView.as_view(),
        name="slo-post",
    ),
    # Metadata
    path(
        "<slug:application_slug>/metadata/",
        metadata.MetadataDownload.as_view(),
        name="metadata-download",
    ),
]

# WSFed urlpatterns
wsfed_urlpatterns = [
    path(
        "<slug:application_slug>/wsfed-suse/active/",
        WSFedActiveView.as_view(),
        name="wsfed-active",
    ),
    path(
        "<slug:application_slug>/wsfed-suse/passive/",
        WSFedPassiveView.as_view(),
        name="wsfed-passive",
    ),
    path(
        "<slug:application_slug>/wsfed-suse/sign-out/",
        WSFedSignOutView.as_view(),
        name="wsfed-sign-out",
    ),
    path(
        "<slug:application_slug>/wsfed-suse/mex/",
        WSFedMetadataDownloadView.as_view(),
        name="wsfed-mex",
    ),
]

urlpatterns += wsfed_urlpatterns

api_urlpatterns = [
    ("propertymappings/provider/saml", SAMLPropertyMappingViewSet),
    ("providers/saml", SAMLProviderViewSet),
]
