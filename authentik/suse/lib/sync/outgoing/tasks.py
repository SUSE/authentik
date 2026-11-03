from django.db import transaction
from django.db.models.query import Q
from structlog.stdlib import BoundLogger

from authentik.core.models import User
from authentik.lib.sync.outgoing.exceptions import (
    NotFoundSyncException,
)
from authentik.lib.sync.outgoing.models import OutgoingSyncProvider
from authentik.lib.utils.reflection import class_to_path


def delete_orphaned_users(logger: BoundLogger, provider: OutgoingSyncProvider):
    provider_cls_name = class_to_path(type(provider))
    if provider_cls_name != "authentik.providers.scim.models.SCIMProvider":
        logger.warn(
            "Delete orphaned users is not implemented for this OutgoingSyncProvider",
            provider_cls_name=provider_cls_name,
        )
        return

    user_client = provider.client_for_model(User)

    connections_to_delete = user_client.connection_type.objects.filter(
        Q(provider=provider) & ~Q(user__in=provider.get_object_qs(User).values_list("pk"))
    ).values_list("scim_id", flat=True)

    for scim_id in connections_to_delete.iterator(chunk_size=1_000):
        logger.info("Deleting SCIMUserConnection", scim_id=scim_id, provider_pk=provider.pk)
        # Need a transaction here because SCIMProvider deletes the db entry first
        # and afterward cleans up on the remote
        with transaction.atomic():
            try:
                user_client.delete(scim_id)
            except NotFoundSyncException:
                # User already gone on remote. Ignore and allow transaction to succeed.
                pass
