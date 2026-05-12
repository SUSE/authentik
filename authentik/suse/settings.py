# Infrastructure specific settings

from authentik.lib.config import CONFIG
from authentik.root.settings import DRAMATIQ as BASE_DRAMATIQ

# S3 Configuration
AWS_S3_OBJECT_PARAMETERS = CONFIG.get_dict_from_b64_json("suse.aws_s3_object_parameters", {})
CONFIG.log("info", f"Loaded AWS_S3_OBJECT_PARAMETERS={AWS_S3_OBJECT_PARAMETERS}")

# Dramatiq config
#
# Configure the Broker
allowed_actors = CONFIG.get("worker.allowed_actors", "")
ignored_actors = CONFIG.get("worker.ignored_actors", "")
broker_class = CONFIG.get("worker.broker_class", "authentik.suse.worker.broker.Broker")
broker_kwargs = {
    "allowed_actors": [q.strip() for q in allowed_actors.split(",") if q.strip() != ""],
    "ignored_actors": [q.strip() for q in ignored_actors.split(",") if q.strip() != ""],
}

# Configure the Scheduler
schedule_model = CONFIG.get("worker.schedule_model", "authentik.tasks.schedules.models.Schedule")
scheduler_class = CONFIG.get(
    "worker.scheduler_class", "authentik.tasks.schedules.scheduler.Scheduler"
)
# Configure the results Backend
result_backend = CONFIG.get("worker.result_backend", "authentik.suse.worker.results.Backend")

# Insert the middleware next to LoggingMiddleware
middleware_pivot = next(
    (
        idx
        for idx, middleware_config in enumerate(BASE_DRAMATIQ["middlewares"])
        if middleware_config[0] == "authentik.tasks.middleware.LoggingMiddleware"
    )
)

middlewares = (
    *(BASE_DRAMATIQ["middlewares"][:middleware_pivot]),
    ("authentik.suse.worker.task_middlewares.AckWithBroker", {}),
    *(BASE_DRAMATIQ["middlewares"][middleware_pivot:]),
)

# Define extras
DRAMATIQ_EXTRAS = {
    "broker_class": broker_class,
    "broker_kwargs": broker_kwargs,
    "result_backend": result_backend,
    "scheduler_class": scheduler_class,
    "schedule_model": schedule_model,
    "middlewares": middlewares,
}

# Extend the default dramatiq configuration
DRAMATIQ = {}
DRAMATIQ.update(BASE_DRAMATIQ)
DRAMATIQ.update(DRAMATIQ_EXTRAS)

CONFIG.log("info", f"Loaded Dramatiq with settings DRAMATIQ={DRAMATIQ})")
