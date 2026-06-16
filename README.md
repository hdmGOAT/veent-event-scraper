# Veent Event Scraper

Django project for scraping events & venues and displaying them in a web UI.

## Stack

- Django 6 + SQLite (dev)
- `requests` + `beautifulsoup4` / `lxml` for scraping

## Layout

```
config/                 Django project settings, root URLConf
events/                 Main app
  models.py             Event & Venue models (with scraping provenance fields)
  views.py              List/detail views with search
  admin.py              Admin registrations
  urls.py               App URLs
  scrapers/             Scraper framework
    base.py             BaseScraper + ScrapedEvent/ScrapedVenue + upsert logic
    example.py          Reference scraper (yields demo data)
    __init__.py         SCRAPERS registry
  management/commands/
    scrape.py           `manage.py scrape` command
templates/              Server-rendered UI (base + event/venue pages)
```

## Setup

```bash
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin
```

## Run

```bash
python manage.py runserver
```

- UI:    http://127.0.0.1:8000/
- Admin: http://127.0.0.1:8000/admin/

## Scraping

```bash
python manage.py scrape --list      # list registered scrapers
python manage.py scrape example     # run one scraper
python manage.py scrape             # run all scrapers
```

### Adding a scraper

1. Create `events/scrapers/myscraper.py` with a `BaseScraper` subclass.
2. Set a unique `source` key and implement `fetch()` to yield `ScrapedEvent`
   objects (attach a `ScrapedVenue` via the `venue` field).
3. Register it in `events/scrapers/__init__.py` under the `SCRAPERS` dict.

Dedup/upsert is automatic: set `external_id` on each `ScrapedEvent` and re-runs
update existing rows instead of duplicating them. See `example.py` for the
requests + BeautifulSoup pattern.
