from datetime import UTC

from authentik.suse.ldap.models import SUSELdapSourceSyncState


def suse_get_ldap_filter(provider_pk: str, ldap_filter: str | None) -> str:
    # TODO Rerun everything if the assigned property mapping changes (checksum)

    sync_state = SUSELdapSourceSyncState.objects.filter(ldap_source_id=provider_pk).first()

    if not sync_state:
        return ldap_filter

    last_timestamp = sync_state.last_modify_timestamp.astimezone(UTC).strftime("%Y%m%d%H%M%SZ")
    modify_filter = f"(modifyTimestamp>={last_timestamp})"

    if ldap_filter:
        return f"(&{modify_filter}{ldap_filter})"

    return modify_filter
