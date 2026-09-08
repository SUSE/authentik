from django.db import models


# Models for permissions only
class SUSECustomer(models.Model):
    class Meta:
        # No database table creation or deletion
        # operations will be performed for this model.
        managed = False

    def __str__(self):
        return "SUSECustomer permission"
