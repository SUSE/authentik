"""LDAP Sync tasks"""

from django.core.cache import cache
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_dramatiq_postgres.middleware import CurrentTaskNotFound
from dramatiq.actor import actor
from ldap3 import BASE
from structlog.stdlib import get_logger

from authentik.lib.config import CONFIG
from authentik.lib.utils.time import timedelta_from_string
from authentik.sources.ldap.models import LDAPSource
from authentik.sources.ldap.sync.users import UserLDAPSynchronizer
from authentik.tasks.middleware import CurrentTask

LOGGER = get_logger()
CACHE_KEY_PREFIX = "suse.com/sources/ldap/page/"
CACHE_KEY_LAST_SYNC_PREFIX = "suse.com/sources/ldap/last-sync/"


def get_tag_value(input_str, tag, default=None):
    try:
        needle = f"{tag}="
        start = input_str.index(needle) + len(needle)
        end = input_str[start:].index("]")
        return input_str[start : start + end]
    except (ValueError, IndexError):
        return default


# LDAP Sync: Existing single user
def ldap_sync_existing_single_user_direct(source, user, task=LOGGER):
    """Sync a user after from a specific source. It may result on the user record deleted"""
    dn = user.attributes.get("distinguishedName")
    if not dn:
        LOGGER.error(
            "User does not have a distinguishedName, this should really never happen...",
            username=user.username,
            user=user,
        )
        return

    for _entry in UserLDAPSynchronizer(source, task).get_iterator(
        search_base=dn,
        search_filter="(objectClass=*)",
        search_scope=BASE,
    ):
        LOGGER.info("Found user in LDAP, skipping", user=user)
        return

    if source.delete_not_found_objects:
        # Although the DB allows for multiple sources tied to a single user The
        # logic in the synchronizer will _always_ save a single unique
        # identifier in the user record. the following check:
        #
        # if not user.sources.exclude(pk=source.pk).exists():
        #
        # may actually be correct, but leave us with stray users tied to other
        # source but not being aligned to what the user record attributes point
        # to.
        LOGGER.info("User not found in LDAP, deleting!", user=user)
        user.delete()

    else:
        LOGGER.info("User not found in LDAP, skipping", user=user)


@actor(
    description=_("[SUSE][LDAP]: Sync of a single pre-existing user against LDAP"),
)
def ldap_sync_existing_single_user(source_pk, username):
    source = LDAPSource.objects.filter(pk=source_pk).first()
    logger = LOGGER

    try:
        logger = CurrentTask.get_task()
    except CurrentTaskNotFound:
        pass

    if not source:
        LOGGER.warning(
            "LDAP Direct sync failed: source not found",
            source=source,
            source_pk=source_pk,
            username=username,
        )
        return

    return ldap_sync_existing_single_user_direct(source, username, task=logger)


# / LDAP Sync: Existing single user


# LDAP Sync: Existing all known users
def ldap_sync_existing_users_direct(source, task=LOGGER):
    """Fully sync LDAP Source users, may result in users deleted"""
    with source.sync_lock as lock_acquired:
        if not lock_acquired:
            task.info("Slim Synchronization is already running. Skipping")
            LOGGER.debug(
                "Failed to acquire lock for LDAP Slim sync, skipping task", source=source.slug
            )
            return

    for user in source.user_set.all().iterator(chunk_size=1000):
        ldap_sync_existing_single_user_direct(source, user, task=task)


@actor(
    description=_("[SUSE][LDAP]: Sync existing users of a given source against LDAP"),
)
def ldap_sync_existing_users(source_pk):
    source = LDAPSource.objects.filter(pk=source_pk).first()
    logger = LOGGER

    try:
        logger = CurrentTask.get_task()
    except CurrentTaskNotFound:
        pass

    if not source:
        LOGGER.warning(
            "LDAP Direct sync failed: source not found",
            source=source,
            source_pk=source_pk,
        )
        return

    return ldap_sync_existing_users_direct(source, task=logger)


# / LDAP Sync: Existing all known users


# LDAP Slim Sync: Single page
def ldap_slim_sync_user_page_direct(source, entries_page, task=LOGGER):
    """LDAP Slim Sync: Synchronize a single page of entries"""
    synchronizer = UserLDAPSynchronizer(source, task)

    search_scope = BASE
    user_filter = "(objectClass=*)"

    count = 0
    for slim_entry in entries_page:
        dn = slim_entry["dn"]
        found = False
        for entry in synchronizer.get_iterator(
            search_base=dn,
            search_filter=user_filter,
            search_scope=search_scope,
        ):
            found = True
            LOGGER.debug("Synchronizing entry", entry=entry, dn=dn, source=source.slug)
            LOGGER.info("Synchronizing entry", dn=dn, source=source.slug)
            user, created = synchronizer.sync_single_record(entry)
            if not created:
                LOGGER.info("User skipped from synchronization", dn=dn, source=source.slug)

        if not found:
            LOGGER.info("User not found by dn", dn=dn, source=source.slug)
            continue
        count += 1
    return count


@actor(
    description=_("LDAP Slim Sync: cache page sync"),
)
def ldap_slim_sync_user_page(source_slug, page_cache_key, task=LOGGER, preserve_cache=False):
    entries_page = cache.get(page_cache_key)
    source: LDAPSource = LDAPSource.objects.filter(slug=source_slug, enabled=True).first()
    if not source:
        task.info("Source not found", source_slug=source_slug)
        return

    if not entries_page:
        error_message = (
            f"Could not find entries page in cache: {page_cache_key}. "
            + "Try increasing ldap.task_timeout_hours"
        )
        LOGGER.warning(error_message)
        task.error(error_message)
        return
    cache.touch(page_cache_key)
    sync_count = ldap_slim_sync_user_page_direct(source, entries_page, task=task)
    msg = f"Synchronized {sync_count} records from page {page_cache_key}"
    LOGGER.info(msg)
    task.info(msg)
    if not preserve_cache:
        cache.delete(page_cache_key)


# / LDAP Slim Sync: Single page


# LDAP Slim Sync: All directory
def ldap_slim_sync_all_users_direct(source, task=LOGGER, preserve_cache=False, since=None):
    """LDAP Slim Sync: Synchronize all available directory entries"""
    with source.sync_lock as lock_acquired:
        if not lock_acquired:
            task.info("Synchronization is already running. Skipping")
            LOGGER.debug("Failed to acquire lock for LDAP sync, skipping task", source=source.slug)
            return

        now = timezone.now()
        if not since:
            since = cache.get(CACHE_KEY_LAST_SYNC_PREFIX + source.slug)

        if not since:
            since = now - timedelta_from_string(
                get_tag_value(
                    source.name, "since", CONFIG.get("suse.default_ldap_since", "hours=24")
                )
            )

        # minute resolution is more than enough for the usecase.
        now_ts = now.strftime("%Y%m%d%H%M")
        synchronizer = UserLDAPSynchronizer(source, task)
        for idx, page in enumerate(
            synchronizer.get_objects(attributes=["dn"], since=since), start=1
        ):
            page_cache_key = f"{CACHE_KEY_PREFIX}_{now_ts}_{idx}"
            cache.set(page_cache_key, page, 60 * 60 * CONFIG.get_int("ldap.task_timeout_hours"))

            task.info(f"Sending DN page {idx}", source=source.slug, idx=idx)
            LOGGER.info(f"Sending DN page {idx}", source=source.slug, idx=idx)
            ldap_slim_sync_user_page.send_with_options(
                args=(source.slug, page_cache_key),
                kwargs=dict(preserve_cache=preserve_cache),
                uid=f"{source.slug}:{synchronizer.name()}:{now_ts}_{idx}",
            )

        task.info(f"Scheduled {idx} pages")
        LOGGER.info(f"Scheduled {idx} pages")
        cache.set(CACHE_KEY_LAST_SYNC_PREFIX + source.slug, now)


@actor(
    time_limit=(60 * 60 * CONFIG.get_int("ldap.task_timeout_hours") * 1000),
    description=_("LDAP Slim Sync: Full source sync"),
)
def ldap_slim_sync_all_users(source_slug: str, preserve_cache=False, since=None):
    try:
        task = CurrentTask.get_task()
    except CurrentTaskNotFound:
        task = LOGGER

    source: LDAPSource = LDAPSource.objects.filter(slug=source_slug, enabled=True).first()
    if not source:
        task.info("Source not found", source_slug=source_slug)
        return
    ldap_slim_sync_all_users_direct(source, preserve_cache=preserve_cache, since=since)


# / LDAP Slim Sync: All directory
