# n8n Workflow: Veent Scraper Automation

Schedules and runs all 8 Django scrapers daily by calling the `/webhooks/scrape/`
endpoint for each source in sequence.

**Workflow URL:** https://jsrl.app.n8n.cloud/workflow/QVedq95qV8EkOiuE

---

## How it works

```
Schedule Trigger (daily midnight UTC) ─┐
Manual Run Trigger                     ┘
             │
             ▼
  Scrape Google Places Venues     POST /webhooks/scrape/ { source: "google_places" }
             │
  Scrape AllEvents CDO Events     POST /webhooks/scrape/ { source: "allevents_cdo" }
             │
  Scrape HappeningNext CDO        POST /webhooks/scrape/ { source: "happeningnext_cdo" }
             │
  Scrape MyRuntime Events         POST /webhooks/scrape/ { source: "myruntime" }
             │
  Scrape Ticket2Me Events         POST /webhooks/scrape/ { source: "ticket2me" }
             │
  Scrape Planout Events           POST /webhooks/scrape/ { source: "planout" }
             │
  Scrape Racemeister Partner Orgs POST /webhooks/scrape/ { source: "racemeister_partners" }
             │
  Scrape Racemeister Events       POST /webhooks/scrape/ { source: "racemeister_events" }
```

Each HTTP Request node has `continueOnFail: true` — one failing scraper does not
stop the rest of the chain.

---

## Configuration (before activating)

### 1. Update the URL in each HTTP Request node

Open each of the 8 scraper nodes and replace:
```
https://YOUR-DJANGO-DOMAIN.example.com/webhooks/scrape/
```
with your actual Django app URL, e.g.:
```
https://abc123.ngrok.io/webhooks/scrape/
```

All 8 nodes point to the same endpoint — only the `source` field in the JSON body differs.

### 2. Verify the secret

Each node sends the header:
```
X-Scraper-Key: <SCRAPER_WEBHOOK_SECRET>
```

This must match `SCRAPER_WEBHOOK_SECRET` in your `.env`. Change it in both places
if you use a different value.

### 3. Activate

Toggle the workflow to **Active** in n8n. It will then run daily at midnight UTC.

Use **Manual Run** trigger to test without waiting for the schedule.

---

## Node structure (SDK code)

The workflow was created using the n8n Workflow SDK. To recreate or modify it
programmatically, call `create_workflow_from_code` via the n8n MCP server with
this pattern:

```javascript
import { workflow, node, trigger, sticky } from "@n8n/workflow-sdk";

const scheduleTrigger = trigger({
  type: "n8n-nodes-base.scheduleTrigger",
  version: 1.3,
  config: {
    name: "Daily at Midnight UTC",
    parameters: {
      rule: { interval: [{ field: "hours", hoursInterval: 24, triggerAtHour: 0 }] }
    },
    output: [{ timestamp: "2026-06-17T00:00:00.000Z" }]
  }
});

const manualTrigger = trigger({
  type: "n8n-nodes-base.manualTrigger",
  version: 1,
  config: { name: "Manual Run", output: [{}] }
});

// Each scraper follows this pattern:
const scrapeGooglePlaces = node({
  type: "n8n-nodes-base.httpRequest",
  version: 4.3,
  continueOnFail: true,
  config: {
    name: "Scrape Google Places Venues",
    parameters: {
      method: "POST",
      url: "https://YOUR-DJANGO-DOMAIN.example.com/webhooks/scrape/",
      sendHeaders: true,
      headerParameters: {
        parameters: [{ name: "X-Scraper-Key", value: "<SCRAPER_WEBHOOK_SECRET>" }]
      },
      sendBody: true,
      contentType: "json",
      specifyBody: "json",
      jsonBody: "{\"source\": \"google_places\"}"
    },
    output: [{ success: true, source: "google_places", created: 0, updated: 0 }]
  }
});

// ... repeat for each scraper source

export default workflow("veent-scraper-automation", "Veent Scraper Automation")
  .add(scheduleTrigger)
  .to(scrapeGooglePlaces)
  // .to(scrapeAllEvents) ...
  .add(manualTrigger)
  .to(scrapeGooglePlaces);
```

**SDK rules that apply here:**
- Function declarations are not allowed — define each node as a `const`.
- `continueOnFail` goes at the top level of the `node()` call, not inside `config`.
- Both triggers share the same chain via the fan-in pattern (`.add(manualTrigger).to(firstNode)`).

---

## Adding a new scraper to this workflow

1. Add the scraper to Django (see `n8n-webhook-endpoints.md`).
2. In n8n, open the workflow.
3. Add a new HTTP Request node after the last scraper:
   - Method: POST
   - URL: same base URL as the others
   - Header: `X-Scraper-Key: <secret>`
   - Body: `{"source": "<new_source_key>"}`
   - Enable **Continue On Fail**
4. Connect it after `Scrape Racemeister Events`.
5. Save and verify with **Manual Run**.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| 401 Unauthorized | `X-Scraper-Key` doesn't match `SCRAPER_WEBHOOK_SECRET` |
| 400 unknown source | Source key not in `SCRAPERS` registry |
| Connection timeout | Django app not reachable from n8n (check ngrok / tunnel) |
| Scraper node shows error but chain continues | Expected — `continueOnFail: true` is working |
| Playwright scrapers time out | Increase HTTP Request timeout to 300 s+ in the node settings |
