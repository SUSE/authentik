from authentik.blueprints.apps import ManagedAppConfig


class SUSEApiExtension(ManagedAppConfig):
    name = "authentik.suse.api_extensions"
    label = "authentik_suse_api"
    verbose_name = "SUSE API extensions"
    default = True
