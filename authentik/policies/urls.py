"""API URLs"""

from django.urls import path

from authentik.policies.api.policies import PolicyViewSet
from authentik.policies.views import BufferView
from authentik.suse.rbac.policybindings_views import PolicyBindingViewSet

urlpatterns = [
    path("buffer", BufferView.as_view(), name="buffer"),
]

api_urlpatterns = [
    ("policies/all", PolicyViewSet),
    ("policies/bindings", PolicyBindingViewSet),
]
