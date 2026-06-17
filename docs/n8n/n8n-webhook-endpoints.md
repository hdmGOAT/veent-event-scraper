# n8n Webhook Endpoints

Django endpoints that receive calls from n8n workflows. Both are secured with a shared
secret and follow the same auth pattern.

---

## Setup

### 1. Set the secret

Add to `.env` (already present — change the value before production):

```
SCRAPER_WEBHOOK_SECRET=YOUR_WEBHOOK_SECRET_HERE
```

Django loads `.env` automatically at startup via the `_load_dotenv` helper in
`config/settings.py`. The views read the secret directly from `os.environ`:

```python
_WEBHOOK_SECRET = os.environ.get("SCRAPER_WEBHOOK_SECRET", "")
```

If the variable is unset, all webhook requests return 401 (fail-closed).

### 2. Expose Django to the internet (local dev)

n8n cloud cannot reach `localhost`. Use ngrok or Cloudflare Tunnel:

```bash
ngrok http 8000
# or
cloudflared tunnel --url http://localhost:8000
```

Use the generated public URL as the base for all n8n HTTP Request nodes.

---

## Endpoints

### POST `/webhooks/scrape/`

Triggers a single registered scraper by source key. Called by the
**Veent Scraper Automation** workflow.

**Auth header:**
```
X-Scraper-Key: <SCRAPER_WEBHOOK_SECRET>
```

**Request body:**
```json
{ "source": "google_places" }
```

Valid source keys (from `events/scrapers/__init__.py`):

| Key | Scraper | Type |
|---|---|---|
| `google_places` | GooglePlacesVenueScraper | venue-only |
| `allevents_cdo` | AllEventsCDOScraper | events (Playwright) |
| `happeningnext_cdo` | HappeningNextCDOScraper | events (Playwright) |
| `myruntime` | MyRuntimeScraper | events + organizers |
| `ticket2me` | Ticket2MeScraper | events |
| `planout` | PlanoutScraper | events |
| `racemeister_partners` | RacemeisterPartnersScraper | organizers |
| `racemeister_events` | RacemeisterEventsScraper | events |

**Response (success):**
```json
{ "success": true, "source": "google_places", "created": 12, "updated": 3 }
```

**Response (error):**
```json
{ "success": false, "source": "google_places", "error": "API key missing" }
```

The scraper runs **synchronously** — n8n should set a generous HTTP timeout (300 s+)
for Playwright-based scrapers (`allevents_cdo`, `happeningnext_cdo`).

---

### POST `/webhooks/ingest-events/`

Accepts a pre-scraped array of events from AI agents and saves them via the
existing `save_events()` persistence layer. Called by the **AI Event Scraper** workflows.

**Auth header:**
```
X-Scraper-Key: <SCRAPER_WEBHOOK_SECRET>
```

**Request body:**
```json
{
  "source": "luma",
  "events": [
    {
      "name": "Tech Meetup CDO",
      "starts_at": "2026-06-20T18:00:00",
      "ends_at": "2026-06-20T21:00:00",
      "location": "SM City CDO, Cagayan de Oro",
      "url": "https://lu.ma/tech-meetup-cdo",
      "description": "A networking event for tech professionals.",
      "organizer": "CDO Tech Hub",
      "price": "Free",
      "external_id": "tech-meetup-cdo"
    }
  ]
}
```

**Field rules:**

| Field | Required | Notes |
|---|---|---|
| `source` | yes | Arbitrary string used as the provenance key in the DB |
| `events` | yes | Array of event objects |
| `name` | yes | Event title |
| `url` | yes | Full URL to the event page |
| `starts_at` | no | ISO 8601 datetime; naive datetimes are made UTC-aware |
| `ends_at` | no | ISO 8601 datetime |
| `location` | no | Used as venue name if no matching Venue exists |
| `description` | no | Stored in `Event.description` |
| `organizer` | no | Stored in `Event.organizer` (CharField) |
| `price` | no | Stored in `Event.price` (CharField) |
| `external_id` | no | Falls back to `url` when absent; used for upsert dedup |

**Deduplication:** events are upserted on `(source, external_id)`. Running the same
workflow twice will update existing rows rather than create duplicates.

**Response (success):**
```json
{ "success": true, "source": "luma", "created": 8, "updated": 2 }
```

---

## Code changes made

### `events/views.py`

Added at the top:
```python
import json
import os
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
```

Added near the bottom (after the review views):

```python
_WEBHOOK_SECRET = os.environ.get("SCRAPER_WEBHOOK_SECRET", "")

@csrf_exempt
@require_POST
def scraper_webhook(request):
    # ... runs a registered scraper by source key

@csrf_exempt
@require_POST
def ingest_events_webhook(request):
    # ... accepts AI-extracted event arrays and saves via save_events()
```

### `events/urls.py`

Added two paths:
```python
path("webhooks/scrape/", views.scraper_webhook, name="scraper_webhook"),
path("webhooks/ingest-events/", views.ingest_events_webhook, name="ingest_events_webhook"),
```

### `.env`

Added:
```
SCRAPER_WEBHOOK_SECRET=YOUR_WEBHOOK_SECRET_HERE
```

---

## Testing manually

```bash
# From a terminal with Django running on port 8000
curl -X POST http://localhost:8000/webhooks/scrape/ \
  -H "X-Scraper-Key: YOUR_WEBHOOK_SECRET_HERE" \
  -H "Content-Type: application/json" \
  -d '{"source": "myruntime"}'

curl -X POST http://localhost:8000/webhooks/ingest-events/ \
  -H "X-Scraper-Key: YOUR_WEBHOOK_SECRET_HERE" \
  -H "Content-Type: application/json" \
  -d '{"source": "luma", "events": [{"name": "Test Event", "url": "https://lu.ma/test"}]}'
```

---

## Adding a new scraper source

1. Create `events/scrapers/<name>.py` with a `BaseScraper` subclass.
2. Register it in `events/scrapers/__init__.py` under `SCRAPERS`.
3. `scraper_webhook` picks it up automatically — no endpoint change needed.

For AI-sourced data (n8n workflows), just use a new `source` string in the
`ingest-events` body. No Django code change required.
