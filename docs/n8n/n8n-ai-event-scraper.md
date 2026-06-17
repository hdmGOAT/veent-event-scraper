# n8n Workflow: AI Event Scraper

Uses GPT-4o to read a web page and extract structured event data, then saves it to Veent
via the `/webhooks/ingest-events/` endpoint. Designed to be cloned for each new source
(Lu.ma, Facebook, Instagram, TikTok, etc.).

**Current workflow (Lu.ma):** https://jsrl.app.n8n.cloud/workflow/yFwdijIjegInX2Lt

---

## How it works

```
Schedule Trigger (daily 6 AM UTC) ─┐
Manual Run Trigger                  ┘
              │
              ▼
   Fetch Lu.ma via Jina Reader
   GET https://r.jina.ai/https://lu.ma/home
   (Jina renders JavaScript and returns clean markdown)
              │
              ▼
   AI: Extract Events from Lu.ma
   GPT-4o reads the markdown and returns a structured JSON
   array matching the event schema
              │
              ▼
   Format Ingest Payload  (Code node)
   Wraps events in { source: "luma", events: [...] }
              │
              ▼
   Save Events to Veent
   POST /webhooks/ingest-events/
   → Django maps to ScrapedEvent objects → save_events()
```

---

## Why Jina Reader

[Jina Reader](https://jina.ai/reader/) (`r.jina.ai`) is a free service that:
- Fetches any URL, executes JavaScript, and returns clean markdown
- Works on single-page apps that a plain HTTP Request cannot read
- Requires no API key for basic usage

For a site at `https://example.com/events`, the Jina fetch URL is:
```
https://r.jina.ai/https://example.com/events
```

With `Accept: application/json`, the response has this shape:
```json
{
  "data": {
    "title": "Page title",
    "url": "https://example.com/events",
    "content": "# Events\n\n..."
  }
}
```

The `data.content` field (markdown) is what gets passed to the AI.

---

## Event schema (structured output)

The AI agent uses `outputParserStructured` to enforce this schema:

```json
{
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

The AI is instructed to:
- Use ISO 8601 for dates or leave as empty string if unknown
- Only include events that have at least a name and URL
- Return an empty `events` array if the page has no events

---

## Configuration (before activating)

### 1. OpenAI credential

The workflow uses the **n8n free OpenAI API credits** credential, which was
auto-assigned at creation. No extra setup needed unless that credential expires.

### 2. Update the Django URL

In the **Save Events to Veent** node, replace:
```
https://YOUR-DJANGO-DOMAIN.example.com/webhooks/ingest-events/
```
with your actual Django app URL.

### 3. Activate

Toggle the workflow to **Active**. It runs daily at 6 AM UTC.

Use **Manual Run** to test immediately.

---

## SDK code (to recreate or modify)

```javascript
import { workflow, node, trigger, sticky, languageModel, outputParser, newCredential, expr } from "@n8n/workflow-sdk";

const scheduleTrigger = trigger({
  type: "n8n-nodes-base.scheduleTrigger",
  version: 1.3,
  config: {
    name: "Daily at 6 AM UTC",
    parameters: {
      rule: { interval: [{ field: "hours", hoursInterval: 24, triggerAtHour: 6 }] }
    },
    output: [{ timestamp: "2026-06-17T06:00:00.000Z" }]
  }
});

const manualTrigger = trigger({
  type: "n8n-nodes-base.manualTrigger",
  version: 1,
  config: { name: "Manual Run", output: [{}] }
});

const fetchPage = node({
  type: "n8n-nodes-base.httpRequest",
  version: 4.3,
  config: {
    name: "Fetch Lu.ma via Jina Reader",
    parameters: {
      method: "GET",
      url: "https://r.jina.ai/https://lu.ma/home",
      sendHeaders: true,
      headerParameters: {
        parameters: [
          { name: "Accept", value: "application/json" },
          { name: "X-With-Links-Summary", value: "true" }
        ]
      }
    },
    output: [{ data: { title: "", url: "", content: "" } }]
  }
});

const openAiModel = languageModel({
  type: "@n8n/n8n-nodes-langchain.lmChatOpenAi",
  version: 1.3,
  config: {
    name: "OpenAI GPT-4o",
    parameters: { model: expr("{{ \"gpt-4o\" }}") },
    credentials: { openAiApi: newCredential("n8n free OpenAI API credits") }
  }
});

const eventParser = outputParser({
  type: "@n8n/n8n-nodes-langchain.outputParserStructured",
  version: 1.3,
  config: {
    name: "Event Schema Parser",
    parameters: {
      schemaType: "fromJson",
      jsonSchemaExample: "{ \"events\": [{ \"name\": \"\", \"starts_at\": \"\", \"ends_at\": \"\", \"location\": \"\", \"url\": \"\", \"description\": \"\", \"organizer\": \"\", \"price\": \"\", \"external_id\": \"\" }] }"
    }
  }
});

const aiAgent = node({
  type: "@n8n/n8n-nodes-langchain.agent",
  version: 3.1,
  config: {
    name: "AI: Extract Events from Lu.ma",
    parameters: {
      promptType: "define",
      systemMessage: "You are an event data extraction specialist. Extract ALL events from the page. For each: name, starts_at (ISO 8601 or empty), ends_at (ISO 8601 or empty), location, url (full), description (1-2 sentences), organizer, price, external_id (slug from URL). Skip events without name+url.",
      text: expr("Extract all events from this page:\n\n{{ $json.data.content }}"),
      hasOutputParser: true
    },
    subnodes: { model: openAiModel, outputParser: eventParser },
    output: [{ events: [] }]
  }
});

const formatPayload = node({
  type: "n8n-nodes-base.code",
  version: 2,
  config: {
    name: "Format Ingest Payload",
    parameters: {
      mode: "runOnceForAllItems",
      jsCode: "const events = $input.first().json.events || [];\nreturn [{ json: { source: \"luma\", events } }];"
    },
    output: [{ source: "luma", events: [] }]
  }
});

const saveToVeent = node({
  type: "n8n-nodes-base.httpRequest",
  version: 4.3,
  continueOnFail: true,
  config: {
    name: "Save Events to Veent",
    parameters: {
      method: "POST",
      url: "https://YOUR-DJANGO-DOMAIN.example.com/webhooks/ingest-events/",
      sendHeaders: true,
      headerParameters: {
        parameters: [{ name: "X-Scraper-Key", value: "veent-n8n-scraper-2026" }]
      },
      sendBody: true,
      contentType: "json",
      specifyBody: "json",
      jsonBody: expr("{{ JSON.stringify($json) }}")
    },
    output: [{ success: true, source: "luma", created: 0, updated: 0 }]
  }
});

export default workflow("veent-ai-luma-scraper", "AI Event Scraper: Lu.ma")
  .add(scheduleTrigger)
  .to(fetchPage)
  .to(aiAgent)
  .to(formatPayload)
  .to(saveToVeent)
  .add(manualTrigger)
  .to(fetchPage);
```

**SDK rules that apply here:**
- `model` on a `languageModel` node must be wrapped in `expr()`.
- The agent node uses `systemMessage` for instructions and `text` (with `expr()`) for the
  data-carrying user message.
- Code node uses `runOnceForAllItems` when transforming a single batch result.
- `JSON.stringify($json)` in `jsonBody` serializes the full output object as the POST body.

---

## Cloning for a new source

To add another AI-scraped source (e.g. Eventbrite, Meetup):

1. **Duplicate** the Lu.ma workflow in n8n.
2. **Rename** it (e.g. "AI Event Scraper: Eventbrite").
3. In the **Fetch** node, update the Jina URL:
   ```
   https://r.jina.ai/https://www.eventbrite.com/d/philippines/events/
   ```
4. In the **AI Agent** system message, adjust any source-specific hints
   (e.g. Eventbrite uses different date/location formats).
5. In the **Format Ingest Payload** Code node, change `"luma"` to `"eventbrite"`.
6. Update the Django URL in **Save Events to Veent** if needed.
7. Activate.

No Django code changes are required for new sources — the `ingest-events` endpoint
accepts any `source` string.

---

## Notes on Facebook / Instagram / TikTok

These platforms are more complex because:

- They require user login before showing event content.
- They aggressively block headless browsers and scrapers.
- Jina Reader alone may not work for authenticated pages.

Possible approaches when we get there:
- **Facebook Events API** (requires approved app) — structured data, no scraping needed.
- **Instagram / TikTok official APIs** — limited but reliable.
- **Playwright + authenticated session** — run a local browser with a logged-in account
  and expose results via the Django ingest endpoint. This fits the existing architecture.
- **Third-party scraping services** (Apify, Bright Data) — managed browser-based
  scrapers that can handle login walls.

The Django `ingest-events` endpoint is already designed to accept data from any of these
approaches — only the data collection step changes.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Jina returns empty `content` | Page blocked Jina's crawler — try adding `X-No-Cache: true` header |
| AI returns `{ "events": [] }` | Page didn't render event listings (try a more specific URL) |
| AI returns malformed JSON | Increase model quality: switch from `gpt-4o-mini` to `gpt-4o` |
| 401 on ingest endpoint | `X-Scraper-Key` mismatch or `SCRAPER_WEBHOOK_SECRET` not set |
| Events created = 0, updated = 0 | Events array was empty; check AI node output in execution log |
| Duplicate events on re-run | Expected — events are upserted on `(source, external_id)` |
