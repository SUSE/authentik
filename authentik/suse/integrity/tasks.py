from django.db.models import F
from django.utils.translation import gettext_lazy as _
from dramatiq.actor import actor
from structlog.stdlib import get_logger

from authentik.stages.authenticator_email.models import EmailDevice
from authentik.tasks.middleware import CurrentTask

LOGGER = get_logger()


@actor(description=_("Remove invalid email devices."))
def clean_invalid_email_devices():
    self = CurrentTask.get_task()

    num_deleted, _ = EmailDevice.objects.exclude(email=F("user__email")).delete()
    self.info(f"Deleted {num_deleted} mismatched email devices.")
