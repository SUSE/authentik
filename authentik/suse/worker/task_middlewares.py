import os

import pyroscope
from dramatiq.middleware import Middleware

from authentik.suse.worker.base_broker import PostgresBroker


class PyroscopeWorkerMiddleware(Middleware):
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def after_worker_boot(self, broker, worker):
        """Called automatically inside each individual worker process
        immediately after it boots up.
        """
        pyroscope_server = os.getenv("PYROSCOPE_SERVER_ADDRESS")
        if pyroscope_server:
            pyroscope.configure(
                application_name="authentik-worker",
                server_address=pyroscope_server,
                cpu_enabled=True,
                mem_enabled=True,  # Set to True if tracking memory utilization
                **self.kwargs,
            )


class AckWithBroker(Middleware):
    def after_ack(self, broker, message):
        if isinstance(broker, PostgresBroker):
            broker.ack(message)

    def after_nack(self, broker, message):
        if isinstance(broker, PostgresBroker):
            broker.nack(message)
