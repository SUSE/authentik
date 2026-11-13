from authentik.blueprints.apps import ManagedAppConfig
from authentik.tasks.schedules.common import ScheduleSpec


class SUSEIntegrity(ManagedAppConfig):
    name = "authentik.suse.integrity"
    label = "authentik_suse_integrity"
    verbose_name = "Various SUSE integrity checks"
    default = True

    @property
    def tenant_schedule_specs(self) -> list[ScheduleSpec]:
        from authentik.suse.integrity.tasks import clean_invalid_email_devices

        return [
            ScheduleSpec(
                actor=clean_invalid_email_devices,
                crontab="41 03 * * *",
            ),
        ]
