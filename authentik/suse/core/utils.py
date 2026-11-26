from django.conf import settings

from authentik.core.models import User


def get_suse_user_settings(user: User, base_user_settings: dict) -> dict:
    """Enrich UserSelfSerializer.settings with configured extra user attributes."""
    user_settings = dict(base_user_settings)

    for attr in settings.SUSE_IDENTIFICATION_EXTRA_USER_ATTRIBUTES:
        if value := user.attributes.get(attr):
            user_settings.setdefault(attr, value)

    return user_settings
