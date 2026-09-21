from django.utils.translation import gettext as _
from rest_framework.serializers import ValidationError


def user_in_allowed_rdns(group, user):
    allowed_rdns = group.attributes.get("allowed_rdns", [])

    # If group doesn't have a restriction. it behaves like a normal group
    if not allowed_rdns:
        return

    # if it does, only users _with_ a DN matching any of the RDNs can be accepted
    user_dn = user.attributes.get("distinguishedName")
    if not user_dn:
        raise ValidationError(_("User doesn't have a distinguishedName. Aborting."))

    for rdn in allowed_rdns:
        if user_dn.endswith(rdn):
            return True

    raise ValidationError(_("User was not part of the allowed RDNs"))
