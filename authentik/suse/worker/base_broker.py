import functools
import logging
import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, ParamSpec, TypeVar, cast

import tenacity
from django.core.exceptions import ImproperlyConfigured
from django.db import (
    DEFAULT_DB_ALIAS,
    DatabaseError,
    InterfaceError,
    OperationalError,
    close_old_connections,
    connections,
    transaction,
)
from django.db.backends.postgresql.base import DatabaseWrapper
from django.db.models import BooleanField, Func, Q, QuerySet, Value
from django.db.models.expressions import F
from django.db.models.sql import UpdateQuery
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.module_loading import import_string
from django_dramatiq_postgres.conf import Conf
from django_dramatiq_postgres.models import CHANNEL_PREFIX, ChannelIdentifier, TaskBase, TaskState
from dramatiq.broker import Broker, Consumer, MessageProxy
from dramatiq.common import compute_backoff, current_millis, dq_name, q_name, xq_name
from dramatiq.errors import ConnectionError, QueueJoinTimeout
from dramatiq.message import Message
from dramatiq.middleware import (
    Middleware,
)
from pglock.core import _cast_lock_id
from psycopg.errors import AdminShutdown, IdleSessionTimeout
from structlog.stdlib import get_logger

logger = get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


DATABASE_ERRORS = (
    AdminShutdown,
    IdleSessionTimeout,
    InterfaceError,
    DatabaseError,
    ConnectionError,
    OperationalError,
)


def channel_name(queue_name: str, identifier: ChannelIdentifier) -> str:
    return f"{CHANNEL_PREFIX}.{queue_name}.{identifier.value}"


def raise_connection_error(func: Callable[P, R]) -> Callable[P, R]:
    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except DATABASE_ERRORS as exc:
            logger.warning("Database error encountered", exc=exc, exc_info=True)
            raise ConnectionError(str(exc)) from exc  # type: ignore[no-untyped-call]

    return wrapper


# Django representation of pg_try_advisory_lock
class PGTryLock(Func):
    arity = 1
    function = "pg_try_advisory_lock"
    output_field = BooleanField()
    conditional = True


class PostgresBroker(Broker):
    queues: set[str]  # type: ignore[assignment]

    def __init__(
        self,
        *args: Any,
        middleware: list[Middleware] | None = None,
        db_alias: str = DEFAULT_DB_ALIAS,
        allowed_actors=None,
        ignored_actors=None,
        **kwargs: Any,
    ) -> None:
        if ignored_actors is None:
            ignored_actors = []
        if allowed_actors is None:
            allowed_actors = []
        super().__init__(*args, middleware=[], **kwargs)  # type: ignore[no-untyped-call,misc]
        self.logger = get_logger(__name__, type(self))

        self.queues = set()
        if allowed_actors and ignored_actors:
            raise ImproperlyConfigured("Can't specify both allowed & ignored actors")

        self.allowed_actors = set(allowed_actors)
        self.ignored_actors = set(ignored_actors)
        self.db_alias = db_alias
        self.middleware = []
        if middleware:
            raise ImproperlyConfigured(
                "Middlewares should be set in django settings, not passed directly to the broker."
            )

    @property
    def connection(self) -> DatabaseWrapper:
        return cast(DatabaseWrapper, connections[self.db_alias])

    @property
    def consumer_class(self) -> "type[_PostgresConsumer]":
        return _PostgresConsumer

    @cached_property
    def model(self) -> type[TaskBase]:
        model: type[TaskBase] = import_string(Conf().task_model)
        return model

    @property
    def query_set(self) -> QuerySet[TaskBase]:
        return self.model._default_manager.using(self.db_alias).defer("message", "result")

    def consume(self, queue_name: str, prefetch: int = 1, timeout: int = 30000) -> Consumer:
        self.declare_queue(queue_name)
        return self.consumer_class(
            broker=self,
            db_alias=self.db_alias,
            queue_name=queue_name,
            prefetch=prefetch,
            timeout=timeout,
        )

    def declare_queue(self, queue_name: str) -> None:
        if queue_name not in self.queues:
            self.emit_before("declare_queue", queue_name)  # type: ignore[no-untyped-call]
            self.queues.add(queue_name)
            # Nothing more to do, all queues are in the same table
            self.emit_after("declare_queue", queue_name)  # type: ignore[no-untyped-call]

    def model_defaults(self, message: Message[Any]) -> dict[str, Any]:
        eta = None
        if "eta" in message.options:
            eta = datetime.fromtimestamp(message.options["eta"] / 1000, tz=UTC)
            del message.options["eta"]
        return {
            "queue_name": message.queue_name,
            "actor_name": message.actor_name,
            "state": TaskState.QUEUED,
            "retries": message.options.get("retries", 0),
            "eta": eta,
        }

    @raise_connection_error
    def ack(self, message):
        if message.options.get("marked_in_consumer"):
            return

        close_old_connections()
        self.logger.debug("ACK-ing (yes) message from Broker", message=message.message_id)
        self.query_set.filter(
            message_id=message.message_id,
        ).update(
            state=TaskState.DONE,
            message=b"",
            mtime=timezone.now(),
            eta=None,
        )

    @raise_connection_error
    def nack(self, message):
        if message.options.get("marked_in_consumer"):
            return

        close_old_connections()
        self.logger.debug("NACK-ing (no) message from Broker", message=message.message_id)
        self.query_set.filter(
            message_id=message.message_id,
        ).update(
            state=TaskState.REJECTED,
            message=message.encode(),
            mtime=timezone.now(),
            eta=None,
        )

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(ConnectionError),
        reraise=True,
        wait=tenacity.wait_random_exponential(multiplier=1, max=5),
        stop=tenacity.stop_after_attempt(3),
        before_sleep=tenacity.before_sleep_log(
            cast(logging.Logger, logger), logging.INFO, exc_info=True
        ),
    )
    @raise_connection_error
    def enqueue(self, message: Message[Any], *, delay: int | None = None) -> Message[Any]:
        queue_name = q_name(message.queue_name)  # type: ignore[no-untyped-call]
        if delay:
            message_eta = current_millis() + delay  # type: ignore[no-untyped-call]
            message.options["eta"] = message_eta

        self.declare_queue(queue_name)
        self.logger.debug(
            "Enqueueing message on queue", message_id=message.message_id, queue=queue_name
        )

        message.options["model_defaults"] = self.model_defaults(message)
        message.options["model_create_defaults"] = {}
        self.emit_before("enqueue", message, delay)  # type: ignore[no-untyped-call]

        with transaction.atomic(using=self.db_alias):
            query = {
                "message_id": message.message_id,
            }
            defaults = message.options.pop("model_defaults")
            defaults["message"] = message.encode()
            create_defaults = {
                **query,
                **defaults,
                **message.options.pop("model_create_defaults"),
            }

            task, created = self.query_set.update_or_create(
                **query,
                defaults=defaults,
                create_defaults=create_defaults,
            )
            message.options["task"] = task
            message.options["task_created"] = created

            self.emit_after("enqueue", message, delay)  # type: ignore[no-untyped-call]
        return message

    def get_declared_queues(self) -> set[str]:
        return self.queues.copy()

    def flush(self, queue_name: str) -> None:
        self.query_set.filter(
            queue_name__in=(queue_name, dq_name(queue_name), xq_name(queue_name))  # type: ignore[no-untyped-call]
        ).delete()

    def flush_all(self) -> None:
        for queue_name in self.queues:
            self.flush(queue_name)

    def join(
        self,
        queue_name: str,
        interval: int = 100,
        *,
        timeout: int | None = None,
    ) -> None:
        deadline = timeout and time.monotonic() + timeout / 1000
        while True:
            if deadline and time.monotonic() >= deadline:
                raise QueueJoinTimeout(queue_name)  # type: ignore[no-untyped-call]

            if (
                not self.query_set.filter(queue_name=queue_name)
                .exclude(state__in=(TaskState.DONE, TaskState.REJECTED))
                .exists()
            ):
                return

            time.sleep(interval / 1000)


class _PostgresConsumer(Consumer):
    def __init__(
        self,
        *args: Any,
        broker: PostgresBroker,
        db_alias: str,
        queue_name: str,
        prefetch: int,
        timeout: int,
        **kwargs: Any,
    ) -> None:
        self.logger = get_logger(__name__, type(self))

        self.pending: set[str] = set()
        self.broker = broker
        self.db_alias = db_alias
        self.queue_name = queue_name
        self.timeout = timeout // 1000
        self.to_unlock: set[str] = set()
        self.in_processing: set[str] = set()
        self.prefetch = prefetch
        self.misses = 0

        self._locks_connection: DatabaseWrapper | None = None

        self.task_purge_interval = timedelta(seconds=Conf().task_purge_interval)
        self.task_purge_last_run = timezone.now() - self.task_purge_interval

        self.scheduler = None
        if Conf().schedule_model:
            self.scheduler = import_string(Conf().scheduler_class)()
            self.scheduler.broker = self.broker
            self.scheduler_interval = timedelta(seconds=Conf().scheduler_interval)
            self.scheduler_last_run = timezone.now() - self.scheduler_interval

        self.in_processing_lock = threading.Lock()
        self.logger.debug("[WITH THREAD LOCK]")

    @property
    def query_set(self) -> QuerySet[TaskBase]:
        return self.broker.query_set

    @property
    def locks_connection(self) -> DatabaseWrapper:
        if self._locks_connection is not None and self._locks_connection.is_usable():
            return self._locks_connection
        self._locks_connection = cast(DatabaseWrapper, connections.create_connection(self.db_alias))
        return self._locks_connection

    def _get_message_lock_id(self, message_id: str) -> int:
        lock_id = _cast_lock_id(
            f"{channel_name(self.queue_name, ChannelIdentifier.LOCK)}.{message_id}"
        )  # type: ignore[no-untyped-call]
        return cast(int, lock_id)

    def _fetch_pending_messages(self, count) -> set[str]:
        self.logger.debug(
            "Fetching for pending messages",
            count=count,
            queue=self.queue_name,
            allowed_actors=self.broker.allowed_actors,
            ignored_actors=self.broker.ignored_actors,
        )

        condition = Q(queue_name=self.queue_name)
        if self.broker.allowed_actors:
            condition &= Q(actor_name__in=self.broker.allowed_actors)
        if self.broker.ignored_actors:
            condition &= ~(Q(actor_name__in=self.broker.ignored_actors))

        pending = set(
            self.query_set.exclude(message_id__in=self.in_processing)
            .filter(condition)
            .exclude(state__in=(TaskState.DONE, TaskState.REJECTED))
            .exclude(eta__gte=timezone.now() + timedelta(seconds=self.timeout))
            .order_by(F("eta").asc(nulls_first=True))
            .values_list("message_id", flat=True)[:count]
        )
        self.logger.debug(
            "Finished fetching pending messages in queue",
            count=count,
            pending=len(pending),
            queue=self.queue_name,
        )
        return {str(message_id) for message_id in pending}

    def track_in_processing(self, message_id):
        self.logger.debug(
            "Check-in task to in-memory queue",
            message_id=message_id,
        )
        with self.in_processing_lock:
            self.in_processing.add(message_id)

    def discard_in_processing(self, message_id):
        self.logger.debug(
            "Check-out task from in-memory queue",
            message_id=message_id,
        )
        with self.in_processing_lock:
            self.in_processing.discard(message_id)

    def _consume_one(self, message_id: str) -> Message[Any] | None:
        if message_id in self.in_processing:
            self.logger.debug("Message already consumed by self", message_id=message_id)
            return None

        # Put it in the processing queue to avoid showing up in follow-up calls
        # to consume.
        self.track_in_processing(str(message_id))

        # Grab the task
        task: TaskBase | None = (
            self.query_set.defer(None).defer("result").filter(message_id=message_id).first()
        )

        # Bail if not found (likely never happens)
        if task is None:
            self.logger.debug(
                "Task got lost, ignoring it.", message_id=message_id, actor=task.actor_name
            )
            return None

        # Check if we are allowed to process this actor
        if self.broker.allowed_actors and task.actor_name not in self.broker.allowed_actors:
            self.logger.debug(
                "Task not in the allowed_actors list for this broker",
                message_id=message_id,
                actor=task.actor_name,
                allowed_actors=self.broker.allowed_actors,
            )
            return None

        # Check if we should ignore this actor
        if self.broker.ignored_actors and task.actor_name in self.broker.ignored_actors:
            self.logger.debug(
                "Task in the ignored_actors list for this broker",
                message_id=message_id,
                actor=task.actor_name,
                ignored_actors=self.broker.ignored_actors,
            )
            return None

        # now that we _really_ work on it, try locking the row.
        with self.locks_connection.cursor() as cursor:
            criteria = (
                Q(message_id=message_id)
                & (~Q(state__in=[TaskState.DONE, TaskState.REJECTED]))
                & (
                    Q(eta__lt=timezone.now() + timedelta(seconds=self.timeout))
                    | Q(eta__isnull=True)
                )
                & Q(
                    PGTryLock(
                        Value(self._get_message_lock_id(message_id)), output_field=BooleanField()
                    )
                )
            )

            da_query = self.query_set.filter(criteria).query.chain(UpdateQuery)
            da_query.add_update_values(dict(state=TaskState.CONSUMED.value, mtime=timezone.now()))
            sql, params = da_query.get_compiler(self.query_set.db).as_sql()
            cursor.execute(sql, params)

            if cursor.rowcount != 1:
                # Lock was not successful, mark it for unlock on next iteration
                self._unlock_message(message_id)
                return None

        # Go on normally
        message = Message.decode(cast(bytes, task.message))
        if message.queue_name != task.queue_name:
            message = message.copy(queue_name=task.queue_name)
        message.options["task"] = task
        return message

    @raise_connection_error
    def __next__(self) -> MessageProxy | None:
        self.logger.debug(
            "Consumer loop",
            in_processing=self.in_processing,
            pending=self.pending,
            in_processing_c=len(self.in_processing),
            pending_c=len(self.pending),
        )
        # This method is called every second

        # Run required processes first
        self._scheduler()
        self._purge_locks()

        while True:
            # Try getting a message_id out of the in-flight set
            try:
                message_id = self.pending.pop()

                message = self._consume_one(str(message_id))
                if message is None:
                    self.discard_in_processing(str(message_id))
                    self.logger.debug("Message already consumed. Skipping.", message_id=message_id)
                    return None

                self.misses = 0
                return MessageProxy(message)  # type: ignore[no-untyped-call]
            except KeyError:
                # No more in-flight messages, fetch new ones, but only up to self.prefetch messages.
                messages = []
                processing = len(self.in_processing)
                pending = len(self.pending)
                outstanding_count = pending + processing
                if outstanding_count < self.prefetch:
                    # Fetch up to self.prefetch messages
                    self.pending = messages = self._fetch_pending_messages(
                        self.prefetch - outstanding_count
                    )

                    self.logger.debug(
                        "Job fetching iteration",
                        messages=len(messages),
                    )
                else:
                    # If the pending queue is too full to fetch new messages,
                    # then spend time purging old tasks
                    self._auto_purge()

                if not messages:
                    # If we have too many messages already processing, wait and
                    # don't consume a message straight away, other workers will
                    # be faster.
                    self.misses, backoff_ms = compute_backoff(self.misses, max_backoff=6_000)  # type: ignore[no-untyped-call]
                    self.logger.debug(
                        "Backing off for a bit",
                        processing=processing,
                        backoff_ms=backoff_ms,
                        pending=pending,
                        attempts=self.misses,
                    )
                    time.sleep(backoff_ms / 1000)
                    return None
                # else: retry above, self.pending is guaranteed to have content

    def _unlock_message(self, message_id: str) -> bool:
        self.logger.debug("Unlocking message", message_id=message_id)
        try:
            with self.locks_connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (self._get_message_lock_id(message_id),),
                )
            return True
        except DATABASE_ERRORS:
            self.to_unlock.add(str(message_id))
            return False

    def _post_process_message(self, message: Message[Any], state: TaskState) -> None:
        self.logger.debug("Post-processing message", message=message.message_id, state=state)
        self.logger.debug(
            "Removing from the in-memory queue", message=message.message_id, state=state
        )
        self.discard_in_processing(str(message.message_id))
        self.to_unlock.add(str(message.message_id))

        self.logger.debug("Marking it in the DB", message=message.message_id, state=state)
        self.query_set.filter(
            message_id=message.message_id,
        ).update(
            state=state,
            mtime=timezone.now(),
            eta=None,
        )
        message.options["marked_in_consumer"] = True

    @raise_connection_error
    def ack(self, message: Message[Any]) -> None:
        self._post_process_message(message, TaskState.DONE)

    @raise_connection_error
    def nack(self, message: Message[Any]) -> None:
        self._post_process_message(message, TaskState.REJECTED)

    @raise_connection_error
    def requeue(self, messages: Iterable[Message[Any]]) -> None:
        self.query_set.filter(
            message_id__in=[message.message_id for message in messages],
        ).update(
            state=TaskState.QUEUED,
        )
        for message in messages:
            self.to_unlock.add(str(message.message_id))
            self.discard_in_processing(str(message.message_id))

    def _scheduler(self) -> None:
        if not self.scheduler:
            return
        if timezone.now() - self.scheduler_last_run < self.scheduler_interval:
            return
        self.scheduler.run()
        self.scheduler_last_run = timezone.now()

    def _purge_locks(self) -> None:
        while True:
            try:
                message_id = self.to_unlock.pop()
            except KeyError:
                break
            if not self._unlock_message(str(message_id)):
                return

    def _auto_purge(self) -> None:
        if timezone.now() - self.task_purge_last_run < self.task_purge_interval:
            return
        self.logger.debug("Running garbage collector")
        count = self.query_set.filter(
            state__in=(TaskState.DONE, TaskState.REJECTED),
            mtime__lte=timezone.now() - timedelta(seconds=Conf().task_expiration),
            result_expiry__lte=timezone.now(),
        ).delete()
        self.logger.info("Purged messages in all queues", count=count)
        self.task_purge_last_run = timezone.now()

    @raise_connection_error
    def close(self) -> None:
        try:
            self._purge_locks()
        finally:
            if self._locks_connection is not None:
                conn = self._locks_connection
                self._locks_connection = None
                try:
                    conn.close()
                except DATABASE_ERRORS:
                    pass
            try:
                connections.close_all()
            except DATABASE_ERRORS:
                pass
