from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0018_alter_organizer_enrichment_help_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='scraperrun',
            name='log_output',
            field=models.TextField(blank=True),
        ),
    ]
