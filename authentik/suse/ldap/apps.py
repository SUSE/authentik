from django.apps import AppConfig

from authentik.tasks.schedules.common import ScheduleSpec


class LdapConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "authentik.suse.ldap"

    @property
    def tenant_schedule_specs(self) -> list[ScheduleSpec]:
        return []

    @property
    def global_schedule_specs(self) -> list[ScheduleSpec]:
        return []
