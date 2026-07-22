"""authentik database backend"""
import logging
from typing import Iterable

from django.core.checks import Warning
from django.db.backends.base.validation import BaseDatabaseValidation
from django.db.backends.postgresql.base import DatabaseWrapper as PgBaseDatabaseWrapper
from django_tenants.postgresql_backend.base import DatabaseWrapper as BaseDatabaseWrapper
from prometheus_client import Metric

from prometheus_client.core import REGISTRY, GaugeMetricFamily
from prometheus_client.registry import Collector

from authentik.lib.config import CONFIG


class DatabaseValidation(BaseDatabaseValidation):

    def check(self, **kwargs):
        return self._check_encoding()

    def _check_encoding(self):
        """Throw a warning when the server_encoding is not UTF-8 or
        server_encoding and client_encoding are mismatched"""
        messages = []
        with self.connection.cursor() as cursor:
            cursor.execute("SHOW server_encoding;")
            server_encoding = cursor.fetchone()[0]
            cursor.execute("SHOW client_encoding;")
            client_encoding = cursor.fetchone()[0]
            if server_encoding != client_encoding:
                messages.append(
                    Warning(
                        "PostgreSQL Server and Client encoding are mismatched: Server: "
                        f"{server_encoding}, Client: {client_encoding}",
                        id="ak.db.W001",
                    )
                )
            if server_encoding != "UTF8":
                messages.append(
                    Warning(
                        f"PostgreSQL Server encoding is not UTF8: {server_encoding}",
                        id="ak.db.W002",
                    )
                )
        return messages
from structlog.stdlib import get_logger
LOGGER = get_logger()

collector_instances = {}

class PoolCollector(Collector):
    def __init__(self, db):
        self.db = db

        count = collector_instances.setdefault(db.alias, 0)
        collector_instances[db.alias] = count + 1
        self.index = count

    def collect(self) -> Iterable[Metric]:
        for alias, pool in self.db._connection_pools.items():
            #LOGGER.warning(f"Collecting metrics {self.db.alias}")
            for key, value in pool.get_stats().items():
                yield GaugeMetricFamily(
                    f"psycopg_pool_{self.db.alias}{self.index}_{alias}_{key}", "See psycopg Pool metrics", value=value
                )

INSTANTIATION_COUNTER = 0

class DatabaseWrapper(BaseDatabaseWrapper, Collector):
    """database backend which supports rotating credentials"""
    validation_class = DatabaseValidation

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        global INSTANTIATION_COUNTER
        INSTANTIATION_COUNTER = INSTANTIATION_COUNTER + 1
        self.instance_id = INSTANTIATION_COUNTER

        # TODO Should actually only register the instance that's actually doing the work, not all the introspection instances etc
        REGISTRY.register(self)

    #def get_new_connection(self, *args, **kwargs):
        #if not self.registered:
            #LOGGER.warning("TYPE %s", type(self).)
            #self.registered = True
            #REGISTRY.register(self)

     #   return super().get_new_connection(*args, **kwargs)

    def collect(self) -> Iterable[Metric]:
        #yield GaugeMetricFamily(
        #    f"psycopg_pool_{self.alias}_{self.instance_id}_demo", "See psycopg Pool metrics", value=1
        #)

        for key, value in self.pool.get_stats().items():
            yield GaugeMetricFamily(
                f"psycopg_pool_{self.alias}_{self.instance_id}_{key}", "See psycopg Pool metrics", value=value
            )

    def get_connection_params(self):
        """Refresh DB credentials before getting connection params"""
        conn_params = super().get_connection_params()

        prefix = "postgresql"
        if self.alias.startswith("replica_"):
            prefix = f"postgresql.read_replicas.{self.alias.removeprefix('replica_')}"

        for setting in ("host", "port", "user", "password"):
            conn_params[setting] = CONFIG.refresh(f"{prefix}.{setting}")
            if conn_params[setting] is None and self.alias.startswith("replica_"):
                conn_params[setting] = CONFIG.refresh(f"postgresql.{setting}")

        return conn_params
