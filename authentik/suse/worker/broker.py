from django.db.models import QuerySet
from structlog.stdlib import get_logger

from authentik.suse.worker.base_broker import PostgresBroker

LOGGER = get_logger()


class Broker(PostgresBroker):
    @property
    def query_set(self) -> QuerySet:
        return super().query_set.select_related("tenant").filter(tenant__ready=True)
