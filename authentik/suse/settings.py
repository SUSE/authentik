# Infrastructure specific settings
from pathlib import Path

from authentik.lib.config import CONFIG
from authentik.lib.utils.time import timedelta_from_string

# S3 Configuration
AWS_S3_OBJECT_PARAMETERS = CONFIG.get_dict_from_b64_json("suse.aws_s3_object_parameters", {})
CONFIG.log("info", f"Loaded AWS_S3_OBJECT_PARAMETERS={AWS_S3_OBJECT_PARAMETERS}")

# Not the most beautiful here, copying from authentik.root.settings. it's not
# possible to import here the module because this module is called by
# autentik.root.settings itself.

# _update_settings("authentik.suse.settings")

# That forces redefining some vars:

BASE_DIR = Path(__file__).absolute().parent.parent.parent
TEST = False


allowed_actors = CONFIG.get("worker.allowed_actors", "")
ignored_actors = CONFIG.get("worker.ignored_actors", "")
broker_class = CONFIG.get("worker.broker_class", "authentik.suse.worker.broker.Broker")
broker_kwargs = {
    "allowed_actors": [q.strip() for q in allowed_actors.split(",") if q.strip() != ""],
    "ignored_actors": [q.strip() for q in ignored_actors.split(",") if q.strip() != ""],
}

# Dramatiq config
#
# Adding our custom kwargs to the broker instead.
DRAMATIQ = {
    "broker_class": broker_class,
    "broker_kwargs": broker_kwargs,
    "channel_prefix": "authentik",
    "task_model": "authentik.tasks.models.Task",
    "task_purge_interval": timedelta_from_string(
        CONFIG.get("worker.task_purge_interval")
    ).total_seconds(),
    "task_expiration": timedelta_from_string(CONFIG.get("worker.task_expiration")).total_seconds(),
    "autodiscovery": {
        "enabled": True,
        "setup_module": "authentik.tasks.setup",
        "apps_prefix": "authentik",
    },
    "worker": {
        "processes": CONFIG.get_int("worker.processes", 2),
        "threads": CONFIG.get_int("worker.threads", 1),
        "consumer_listen_timeout": timedelta_from_string(
            CONFIG.get("worker.consumer_listen_timeout")
        ).total_seconds(),
        "watch_folder": BASE_DIR / "authentik",
    },
    "result_backend": "authentik.suse.worker.results.Backend",
    "scheduler_class": "authentik.tasks.schedules.scheduler.Scheduler",
    "schedule_model": CONFIG.get(
        "worker.schedule_model", "authentik.tasks.schedules.models.Schedule"
    ),
    "scheduler_interval": timedelta_from_string(
        CONFIG.get("worker.scheduler_interval")
    ).total_seconds(),
    "middlewares": (
        ("django_dramatiq_postgres.middleware.FullyQualifiedActorName", {}),
        ("django_dramatiq_postgres.middleware.DbConnectionMiddleware", {}),
        ("django_dramatiq_postgres.middleware.TaskStateBeforeMiddleware", {}),
        ("dramatiq.middleware.age_limit.AgeLimit", {}),
        (
            "dramatiq.middleware.time_limit.TimeLimit",
            {
                "time_limit": timedelta_from_string(
                    CONFIG.get("worker.task_default_time_limit")
                ).total_seconds()
                * 1000
            },
        ),
        ("dramatiq.middleware.shutdown.ShutdownNotifications", {}),
        ("dramatiq.middleware.callbacks.Callbacks", {}),
        ("dramatiq.middleware.pipelines.Pipelines", {}),
        (
            "dramatiq.middleware.retries.Retries",
            {
                "max_retries": CONFIG.get_int("worker.task_max_retries") if not TEST else 0,
                "max_backoff": 60 * 60 * 1000,  # 1 hour
            },
        ),
        ("dramatiq.results.middleware.Results", {"store_results": True}),
        ("authentik.tasks.middleware.StartupSignalsMiddleware", {}),
        ("authentik.tasks.middleware.CurrentTask", {}),
        ("authentik.tasks.middleware.TenantMiddleware", {}),
        ("authentik.tasks.middleware.ModelDataMiddleware", {}),
        ("authentik.tasks.middleware.TaskLogMiddleware", {}),
        ("authentik.tasks.middleware.LoggingMiddleware", {}),
        ("authentik.suse.worker.task_middlewares.AckWithBroker", {}),
        ("authentik.tasks.middleware.DescriptionMiddleware", {}),
        ("authentik.tasks.middleware.WorkerHealthcheckMiddleware", {}),
        ("authentik.tasks.middleware.WorkerStatusMiddleware", {}),
        (
            "authentik.tasks.middleware.MetricsMiddleware",
            {
                "prefix": "authentik",
            },
        ),
        ("django_dramatiq_postgres.middleware.TaskStateAfterMiddleware", {}),
    ),
    "test": TEST,
}

CONFIG.log("info", f"Loaded Dramatiq with settings DRAMATIQ={DRAMATIQ})")
