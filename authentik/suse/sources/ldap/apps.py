from authentik.blueprints.apps import ManagedAppConfig


class LdapConfig(ManagedAppConfig):
    name = "authentik.suse.sources.ldap"
    label = "authentik_suse_sources_ldap"
    verbose_name = "SUSE LDAP State"
    default = True
