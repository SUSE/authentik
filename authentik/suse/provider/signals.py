from django.db.models.signals import m2m_changed

from authentik.core.models import User
from authentik.lib.sync.outgoing.signals import _CTX_INHIBIT_DISPATCH


def update_user_modified_at(user_pk):
    User.objects.get(pk=user_pk).save()


def model_m2m_changed(sender, instance, action, pk_set, reverse, **kwargs):
    # keep the same behavior as lib.sync.outgoing.signals.py
    if action not in ["post_add", "post_remove"]:
        return
    if _CTX_INHIBIT_DISPATCH.get():
        return

    # reverse: Sender instance is a Group, pk_set is a list of user pks
    # non-reverse: Sender  instance is a User, pk_set is a list of groups
    if reverse:
        for user_pk in list(pk_set):
            update_user_modified_at(user_pk)
    else:
        update_user_modified_at(instance.pk)


# This signal will need tweaking in the 2026.x branch...
m2m_changed.connect(model_m2m_changed, User.ak_groups.through, weak=False)
