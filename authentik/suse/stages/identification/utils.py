from django.conf import settings
from django.db.models import Q


def get_extra_user_attribute_query(uid_value: str, case_insensitive: bool = True) -> Q:
    """Build a Q filter matching configured extra User.attributes keys against uid_value."""
    if not uid_value or not uid_value.strip():
        return Q()

    lookup_suffix = "__iexact" if case_insensitive else "__exact"

    query = Q()

    for attr in settings.SUSE_IDENTIFICATION_EXTRA_USER_ATTRIBUTES:
        attr_parts = attr.split(".")
        if not attr_parts:
            continue

        query |= Q(**{f"attributes__{'__'.join(attr_parts)}{lookup_suffix}": uid_value})

    return query
