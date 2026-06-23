# Facebook Posts Scraper

Scrapes unstructured Facebook posts (pages, groups, keyword searches) and uses a local
LLM via Ollama to detect events and extract structured fields.

Ported from the `veent-fb-scraper` Chrome extension pipeline.
Parent class: `FacebookEventsScraper` (inherits proxy, stealth, browser setup).

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Full Data Flow](#full-data-flow)
3. [Configuration Reference](#configuration-reference)
4. [Changing the LLM](#changing-the-llm)
5. [Authentication — FB Cookies](#authentication--fb-cookies)
6. [Adding Search Queries](#adding-search-queries)
7. [Running the Scraper](#running-the-scraper)
8. [Troubleshooting](#troubleshooting)

---

## How It Works

### Step 1 — Load Cookies

Before opening a browser, the scraper reads `FB_COOKIES_FILE` from `.env` and injects
the session cookies into the Playwright browser context. This authenticates the browser
as the account that exported the cookies — skipping login and 2FA entirely on every run.

Supported cookie file formats:
- **Netscape / cookies.txt** — exported by the "Get cookies.txt LOCALLY" Chrome extension
- **JSON array** — exported by the "Cookie Editor" Chrome extension

### Step 2 — Launch Browser

Playwright launches headless Chromium with:
- `playwright-stealth` — masks automation signals (navigator.webdriver, etc.)
- DataImpulse residential proxy — optional, configured via `DATAIMPULSE_USER/PASS`
- Images and media **blocked** during scraping to save bandwidth (only loaded during login)

### Step 3 — Navigate to Query

Each active `SearchQuery` row (`source='facebook_posts'`) is visited in order:

| Query value | Where it navigates |
|---|---|
| `upcoming events cebu 2026` | `facebook.com/search/posts?q=upcoming+events+cebu+2026` |
| `https://www.facebook.com/SomePage` | Directly to that page |
| `https://www.facebook.com/groups/12345` | Directly to that group |

### Step 4 — Extract Posts

Three JavaScript snippets run inside the browser page:

| Script | Purpose |
|---|---|
| `_DISMISS_MODAL_JS` | Closes login walls, cookie consent overlays |
| `_EXPAND_SEE_MORE_JS` | Clicks all "See more" buttons so full captions are visible |
| `_EXTRACT_POSTS_JS` | Walks `div[dir="auto"]` blocks, finds parent post cards, extracts `post_url`, `author_name`, `raw_caption`, `raw_links` |

The permalink finder tries 4 strategies per post card:
1. `time[datetime]` element → walk up to `a[href]`
2. Walk up looking for `data-href` attributes
3. Any `a[href]` matching post URL patterns
4. Hash of caption (fallback `synth_` prefix — used when FB hides permalinks in search results)

### Step 5 — Pre-filter

Each caption is checked by `_is_eligible()` **before** hitting the LLM:

| Condition | Action |
|---|---|
| Caption shorter than 20 characters | Skip |
| Contains `wts`, `wtb`, `passaway`, "ticket for sale", etc. | Skip (resale post) |
| Starts with "follow us", "stream now", "out now", etc. | Skip (slop) |

### Step 6 — LLM Structuring (Ollama)

Posts that pass the pre-filter are sent to Ollama:

```
POST http://localhost:11434/api/generate
{
  "model": "llama3.2:3b",
  "prompt": "...",
  "stream": false
}
```

The prompt asks the model for a JSON response with these fields:

```json
{
  "is_event":          true,
  "title":             "Hillsong Worship",
  "start_datetime":    "2026-09-18T20:00:00",
  "venue_name":        "SM Seaside Cebu Arena",
  "city_location":     "Cebu",
  "organizer_name":    "ARC Productions",
  "organizer_email":   null,
  "organizer_phone":   "+63912345678",
  "short_description": "Hillsong Worship live concert at SM Seaside Cebu.",
  "registration_url":  "https://www.smtickets.com/events/30319"
}
```

If `is_event` is `false` the post is discarded. If Ollama is offline or returns
unparseable output, a fallback minimal record is saved so no post is silently lost.

### Step 7 — Save to Database

Structured events are upserted via `save_events()` into the `Event` table.
Organizer names/contacts are saved via `save_organizers()`.
`SearchQuery.last_run_at` and `events_found_count` are updated after each query.

---

## Full Data Flow

```
.env: FB_COOKIES_FILE
        |
        v
Playwright (headless Chromium)
  + playwright-stealth
  + DataImpulse proxy (optional)
  + images BLOCKED after auth
        |
        v
facebook.com/search/posts?q=<query>   (or direct page/group URL)
        |
        v
_DISMISS_MODAL_JS
_EXPAND_SEE_MORE_JS
_EXTRACT_POSTS_JS
        |
        | [{post_url, author_name, raw_caption, raw_links}, ...]
        v
_is_eligible()
  -- resale / slop / too short --> SKIP
        |
        v
Ollama HTTP API  (OLLAMA_BASE / OLLAMA_MODEL)
  -- is_event: false --> SKIP
        |
        v
save_events()  -->  Event table (PostgreSQL / Neon)
save_organizers()  -->  Organizer table
```

---

## Configuration Reference

All settings go in `apps/backend/.env`.

### LLM (Ollama)

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.2:3b` | Model name as shown in `ollama list` |
| `OLLAMA_TIMEOUT` | `90` | Per-request timeout in seconds |

### Facebook Authentication

| Variable | Default | Description |
|---|---|---|
| `FB_COOKIES_FILE` | _(empty)_ | Path to exported cookies file (Netscape or JSON) |
| `FB_HEADLESS` | `true` | Set to `false` to watch the browser window |
| `ACC_EMAIL` | _(empty)_ | FB account email (used if no cookie file is set) |
| `ACC_PASSWORD` | _(empty)_ | FB account password |
| `FB_PROFILE_DIR` | _(empty)_ | Persistent Chromium profile dir (survives 2FA) |

### Proxy (DataImpulse)

| Variable | Default | Description |
|---|---|---|
| `DATAIMPULSE_USER` | _(empty)_ | Proxy username (leave empty to disable proxy) |
| `DATAIMPULSE_PASS` | _(empty)_ | Proxy password |
| `DATAIMPULSE_HOST` | `gw.dataimpulse.com` | Proxy host |
| `DATAIMPULSE_PORT` | `823` | Proxy port |

---

## Changing the LLM

### Use a different Ollama model

1. Pull the model you want:
   ```bash
   ollama pull mistral
   # or
   ollama pull llama3:8b
   # or
   ollama pull gemma3:4b
   ```

2. Update `.env`:
   ```
   OLLAMA_MODEL=mistral
   ```

3. Run the scraper — no code changes needed.

### Use a remote Ollama instance

If another machine on your network runs Ollama:

```
OLLAMA_BASE=http://192.168.1.50:11434
OLLAMA_MODEL=llama3:8b
```

### Use LM Studio or any OpenAI-compatible server

LM Studio and similar tools expose an OpenAI-compatible API.
You need to adapt `_call_llm_structure` in
`apps/backend/events/scrapers/facebook_posts.py` to use the `/v1/chat/completions`
endpoint instead of `/api/generate`.

Replace the request body:
```python
# Ollama  (current)
payload = json.dumps({
    "model": model,
    "prompt": prompt,
    "stream": False,
}).encode()
# endpoint: f"{base}/api/generate"
# response key: data["response"]

# OpenAI-compatible  (LM Studio / vLLM / llama.cpp server)
payload = json.dumps({
    "model": model,
    "messages": [{"role": "user", "content": prompt}],
    "stream": False,
}).encode()
# endpoint: f"{base}/v1/chat/completions"
# response key: data["choices"][0]["message"]["content"]
```

### Performance tips for small models

`llama3.2:3b` is fast on CPU but gives less consistent JSON output than larger models.
If you see `unparseable output` warnings:

- Try `llama3.2:3b-instruct-q8_0` for better instruction following
- Or `mistral` / `gemma3:4b` if your machine has more RAM
- Increase `OLLAMA_TIMEOUT` if the model is slow to respond (default 90s)

The prompt already instructs the model to return **only** a JSON object with no prose
or markdown. Most 3B+ instruction-tuned models handle this reliably.

---

## Authentication — FB Cookies

Facebook does not serve post content to unauthenticated sessions (posts, groups, search
results are all client-side rendered and gated behind login). Cookies are required.

### Export cookies (recommended)

1. Log into Facebook in your regular Chrome browser.
2. Install the **"Get cookies.txt LOCALLY"** extension.
3. Click the extension icon while on `facebook.com` → **Export**.
4. Save the file (e.g. `www.facebook.com_cookies.txt`) anywhere accessible.
5. Set in `.env`:
   ```
   FB_COOKIES_FILE=../../www.facebook.com_cookies.txt
   ```
   Path is relative to `apps/backend/` (where `manage.py` runs).

### Cookie expiry

FB session cookies typically last 30–90 days. When they expire you will see:

```
page: ... | title: Facebook    ← no notification count, means not logged in
'<query>': 0 raw posts extracted
```

Re-export from your browser and replace the file.

### Alternative: persistent browser profile

For accounts with 2FA, use a persistent Chromium profile so 2FA only needs completing
once:

1. Set in `.env`:
   ```
   FB_HEADLESS=false
   FB_PROFILE_DIR=scripts/fb_profile
   ```

2. Run the scraper — a visible browser opens and logs in with `ACC_EMAIL`/`ACC_PASSWORD`.

3. Complete 2FA in the browser window when prompted (3-minute window).

4. After login the profile is saved. Future runs load the profile silently with
   `FB_HEADLESS=true` — no 2FA required until the session expires.

---

## Adding Search Queries

Queries are stored in the `SearchQuery` Django model. Use the Django shell or admin:

```bash
cd apps/backend
python manage.py shell
```

```python
from events.models import SearchQuery

# Keyword search
SearchQuery.objects.create(
    source='facebook_posts',
    query='upcoming events cdo 2026',
    is_active=True,
)

# Specific page
SearchQuery.objects.create(
    source='facebook_posts',
    query='https://www.facebook.com/SomeEventsPage',
    is_active=True,
)

# Public group
SearchQuery.objects.create(
    source='facebook_posts',
    query='https://www.facebook.com/groups/cebueventsPH',
    is_active=True,
)
```

**Keyword searches** work best — FB exposes more content in search results than on
individual pages, and the search API is more consistent across different FB UI versions.

**Page/group URLs** work when the page has a public feed. If a page redirects or shows
no posts, try navigating to `<page_url>/posts` manually in your browser to check.

---

## Running the Scraper

```bash
cd apps/backend

# Run all active queries
python manage.py scrape facebook_posts

# Limit posts per query (useful for testing)
python manage.py scrape facebook_posts --max-events 5

# Run a specific SearchQuery by ID
python manage.py scrape facebook_posts --query-id 64
```

---

## Troubleshooting

### `0 raw posts extracted` — not logged in

**Symptom:** Page title shows `Facebook` with no notification count `(3)`.

**Fix:** Re-export your FB cookies and update `FB_COOKIES_FILE`.

---

### `Ollama unreachable at http://localhost:11434`

**Fix:** Start Ollama:
```bash
ollama serve
```
Then confirm your model is pulled:
```bash
ollama list
```

---

### `unparseable output` warnings — bad JSON from model

**Cause:** Small models sometimes wrap JSON in markdown or add extra prose.

**Fix options:**
- Switch to a larger/better instruction model (`OLLAMA_MODEL=mistral`)
- Increase timeout (`OLLAMA_TIMEOUT=120`)
- The scraper will still save a fallback record so data is not lost

---

### `ERR_PROXY_AUTH_UNSUPPORTED` or `TRAFFIC_EXHAUSTED`

**Cause:** DataImpulse proxy credentials are wrong or the account ran out of bandwidth.

**Fix:** Top up at [dataimpulse.com](https://dataimpulse.com) or disable the proxy by
commenting out `DATAIMPULSE_USER` / `DATAIMPULSE_PASS` in `.env`. Without the proxy,
Facebook may rate-limit or block datacenter IP ranges — use cookies from an account
that has already established trust from a residential IP.

---

### `2FA checkpoint detected but FB_HEADLESS=true`

**Fix:** Set `FB_HEADLESS=false` and `FB_PROFILE_DIR=scripts/fb_profile` in `.env`,
re-run, complete 2FA in the browser window, then switch back to `FB_HEADLESS=true`.
The profile retains the session until it expires.

---

### Unicode garbled titles (`\U0001d5dc\U0001d5e7...`)

**Cause:** Some FB posts use Unicode Mathematical Bold/Italic characters for styling.
The title is stored as-is in the database. This is cosmetic only — the event data is
correct. A normalisation step can strip these if needed.
