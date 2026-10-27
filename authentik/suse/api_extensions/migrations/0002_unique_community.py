from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ("authentik_suse_api", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX suse_community_uid_unique ON authentik_core_user (lower(attributes ->> 'communityUid'));
                """
        ),
    ]
