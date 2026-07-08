from django.apps import AppConfig

from authentik.tasks.schedules.common import ScheduleSpec


class SCIMProviderStateConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "authentik.suse.provider"

    @property
    def tenant_schedule_specs(self) -> list[ScheduleSpec]:
        return []

    @property
    def global_schedule_specs(self) -> list[ScheduleSpec]:
        return []
