from dramatiq.middleware import Middleware

from authentik.suse.worker.base_broker import PostgresBroker


class AckWithBroker(Middleware):
    def after_ack(self, broker, message):
        if isinstance(broker, PostgresBroker):
            broker.ack(message)

    def after_nack(self, broker, message):
        if isinstance(broker, PostgresBroker):
            broker.nack(message)
