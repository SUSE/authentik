from uuid import uuid4

from django.db import models


class SUSELdapSourceSyncState(models.Model):
    # Should actually be foreign key.
    # But in an effort to keep our models independent let's ignore that for now.
    ldap_source_id = models.UUIDField(primary_key=True, editable=False, default=uuid4)
    last_modify_timestamp = models.DateTimeField("Last processed modify timestamp in LDAP")

    class Meta:
        db_table = "suse_source_ldap_state"

    def __str__(self):
        return f"{self.ldap_source_id} ({self.last_modify_timestamp})"
