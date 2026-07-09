from authentik.blueprints.apps import ManagedAppConfig

from authentik.tasks.schedules.common import ScheduleSpec


class LdapConfig(ManagedAppConfig):
    name = "authentik.suse.ldap"
    label = "authentik_suse_ldap"
    verbose_name = "SUSE LDAP State"
    default = True
