from authentik.blueprints.apps import ManagedAppConfig


class SUSEProviderSyncState(ManagedAppConfig):
    name = "authentik.suse.provider"
    label = "authentik_suse_provider"
    verbose_name = "SUSE Provider State"
    default = True
