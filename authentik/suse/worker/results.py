from django.db import close_old_connections
from django_dramatiq_postgres.results import PostgresBackend


class Backend(PostgresBackend):
    @property
    def query_set(self):
        close_old_connections()
        return super().query_set
