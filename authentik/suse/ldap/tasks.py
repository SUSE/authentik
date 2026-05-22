"""LDAP Sync tasks"""

from django.utils.translation import gettext_lazy as _
from django_dramatiq_postgres.middleware import CurrentTaskNotFound
from dramatiq.actor import actor
from structlog.stdlib import get_logger

from authentik.core.models import User
from authentik.sources.ldap.models import LDAPSource
from authentik.sources.ldap.sync.users import UserLDAPSynchronizer
from authentik.tasks.middleware import CurrentTask

LOGGER = get_logger()


def get_tag_value(input_str, tag, default=None):
    try:
        needle = f"{tag}="
        start = input_str.index(needle) + len(needle)
        end = input_str[start:].index("]")
        return input_str[start : start + end]
    except (ValueError, IndexError):
        return default


def ldap_trigger_jit_sync_direct(source, username, task=LOGGER):
    """Sync a user after from a specific source. It may result on the user record deleted"""
    synchronizer = UserLDAPSynchronizer(source, task)
    preexisting_user = User.objects.filter(username=username).first()
    found = False

    # Grab the user id filter attribute from name tags
    user_id_attribute = get_tag_value(source.name, "uid", "uid")
    user_filter, search_base = synchronizer.get_filter_and_base(user_id_attribute, username)

    if preexisting_user:
        dn = preexisting_user.attributes.get("distinguishedName")
        if not dn:
            LOGGER.error(
                "User does not have a distinguishedName, this should really never happen..."
            )
            return
        user_filter, search_base = synchronizer.get_filter_and_base(dn=dn)

    for entry in synchronizer.get_iterator(
        search_base=search_base,
        search_filter=user_filter,
    ):
        if found:
            LOGGER.warning(
                "LDAP Direct sync returned more than one record, skipping processing more users.",
                username=username,
                user_id_attribute=user_id_attribute,
                user_filter=user_filter,
                search_base=synchronizer.base_dn_users,
            )
            return
        found = True

        user, created = synchronizer.sync_single_record(entry)
        if not user:
            continue
        return user

    LOGGER.warning(
        "LDAP Direct sync failed: User not found in LDAP",
        username=username,
        user_id_attribute=user_id_attribute,
        user_filter=user_filter,
        search_base=synchronizer.base_dn_users,
    )

    if source.delete_not_found_objects and preexisting_user:
        task.warning(
            "LDAP JIT sync failed for username, deleting user.",
            username=username,
            user_id_attribute=user_id_attribute,
            user_filter=user_filter,
            search_base=synchronizer.base_dn_users,
        )
        preexisting_user.delete()
    return


# TODO(josegomezr): move this to the synchronizer class, decorating is getting too ugly.
def ldap_jit_sync_existing_single_user_direct(source, user, task=LOGGER):
    """Sync a user after from a specific source. It may result on the user record deleted"""
    dn = user.attributes.get("distinguishedName")
    if not dn:
        LOGGER.error(
            "User does not have a distinguishedName, this should really never happen...",
            username=user.username,
            user=user,
        )
        return

    synchronizer = UserLDAPSynchronizer(source, task)

    user_filter, search_base = synchronizer.get_filter_and_base(dn=dn)

    for _entry in synchronizer.get_iterator(
        search_base=search_base,
        search_filter=user_filter,
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


def ldap_jit_sync_existing_users_direct(source, task=LOGGER):
    """Fully sync LDAP Source users, may result in users deleted"""
    with source.sync_lock as lock_acquired:
        if not lock_acquired:
            task.info("JIT Synchronization is already running. Skipping")
            LOGGER.debug(
                "Failed to acquire lock for LDAP JIT sync, skipping task", source=source.slug
            )
            return

    for user in source.user_set.all().iterator(chunk_size=1000):
        ldap_jit_sync_existing_single_user_direct(source, user, task=task)


@actor(
    description=_("JIT sync of a single user from LDAP"),
)
def ldap_trigger_jit_sync(source_pk, username):
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

    return ldap_trigger_jit_sync_direct(source, username, task=logger)


@actor(
    description=_("JIT sync existing users of a given source"),
)
def ldap_jit_sync_existing_users(source_pk):
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

    return ldap_jit_sync_existing_users_direct(source, task=logger)
