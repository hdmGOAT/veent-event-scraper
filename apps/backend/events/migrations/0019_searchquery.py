from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0018_alter_organizer_enrichment_help_text"),
    ]

    operations = [
        migrations.CreateModel(
            name="SearchQuery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("query", models.CharField(max_length=500)),
                ("source", models.CharField(
                    help_text="Scraper key this query belongs to, e.g. 'facebook_events'.",
                    max_length=120,
                )),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                ("events_found_count", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["source", "query"],
            },
        ),
        migrations.AddConstraint(
            model_name="searchquery",
            constraint=models.UniqueConstraint(
                fields=["source", "query"], name="unique_source_query"
            ),
        ),
        migrations.AddField(
            model_name="event",
            name="search_query",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="events",
                to="events.searchquery",
            ),
        ),
    ]
