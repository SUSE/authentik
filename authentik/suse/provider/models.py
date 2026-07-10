from django.db import models


class SUSEProviderSyncState(models.Model):
    # Should actually be foreign key. But in an effort to keep our models independent let's ignore that for now.
    provider_id = models.IntegerField(primary_key=True, editable=False)
    last_modify_timestamp = models.DateTimeField("Last processed modify timestamp in LDAP")

    class Meta:
        db_table = "suse_provider_state"

    def __str__(self):
        return f"{self.provider_id} ({self.last_modify_timestamp})"
