"""authentik URL Configuration"""
from authentik.suse.api_extensions.api.customers import SUSECustomersViewSet

api_urlpatterns = [
    ("suse/customers", SUSECustomersViewSet, "suse_customers"),
]
