import django, os
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
django.setup()
from django.db import connection

with connection.cursor() as cursor:
    for table in ("events_venue", "events_event"):
        cursor.execute("""
            SELECT column_name, data_type, character_maximum_length
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
        """, [table])
        cols = cursor.fetchall()
        print(f"\n=== {table} ===")
        for name, dtype, maxlen in cols:
            print(f"  {name:35s} {dtype}" + (f"({maxlen})" if maxlen else ""))
