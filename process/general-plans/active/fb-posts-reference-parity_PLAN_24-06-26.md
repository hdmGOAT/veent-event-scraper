# fb-posts-reference-parity — Implementation Plan

**Date**: 24-06-26
**Complexity**: COMPLEX (multi-phase, model/migration + scraper + LLM + management command)
**Status**: CODE DONE

> Context consulted: `process/context/all-context.md`, `process/context/tests/all-tests.md`,
> `apps/backend/events/scrapers/facebook_posts.py`, `apps/backend/events/models.py`,
> `apps/backend/events/scrapers/base.py`, `apps/backend/events/views.py`,
> `/Volumes/Extreme_SSD/Work/Veent/FB Scraper/fb-events-tool/server/routes/events-posts.js`,
> `/Volumes/Extreme_SSD/Work/Veent/FB Scraper/fb-events-tool/server/lib/llm.js`.

---

## Overview

Five targeted improvements to bring `apps/backend/events/scrapers/facebook_posts.py` to parity
with the reference Node project (`fb-events-tool`) and fix two visible output problems in the
Google-Sheets pipeline:

- **Event names / summaries that are raw hashtag dumps** — caused by LLM returning `is_event=true`
  but `title=null` on hashtag-heavy captions, triggering the fallback `author: caption[:80]` /
  `caption[:500]` assignment. Fix: skip title-less event posts at persistence time; add an explicit
  prompt rule for hashtag-only captions.

- **Fake post links (`/fbpost/posts/synth_<hash>`)** — caused by FB hiding permalink anchors on
  the `/search/posts` surface; the JS `_EXTRACT_POSTS_JS` synthesises a dedup key instead.
  Fix: keep the synth string as `external_id` for dedup but replace the saved `Event.url` with
  a search-link fallback derived from the clean title.

The remaining three items are direct reference ports:

- **Content dedup by normalized title** (mirrors `events-posts.js:146-171`).
- **Ground-truth fabrication rejection for phone/email** (mirrors `llm.js:200-253`).
- **`enriched_at` marker + `enrich_fb_posts` management command** (mirrors `events-posts.js:174,222`).

**`.env` model fix is already done** (`OLLAMA_MODEL=qwen2.5:7b-instruct`). Do NOT re-do it.

---

## Quick Links

- [Goals and Success Metrics](#goals-and-success-metrics)
- [Phase Completion Rules](#phase-completion-rules)
- [Scope](#scope)
- [Phase 1 — Migration: add `Event.enriched_at`](#phase-1--migration-add-eventenriched_at)
- [Phase 2 — Scraper persistence fixes (title-skip, synth-URL, title dedup)](#phase-2--scraper-persistence-fixes)
- [Phase 3 — LLM fabrication rejection + prompt tightening](#phase-3--llm-fabrication-rejection--prompt-tightening)
- [Phase 4 — `enrich_fb_posts` management command](#phase-4--enrich_fb_posts-management-command)
- [Touchpoints](#touchpoints)
- [Public Contracts](#public-contracts)
- [Blast Radius](#blast-radius)
- [Verification Evidence](#verification-evidence)
- [Resume and Execution Handoff](#resume-and-execution-handoff)

---

## Goals and Success Metrics

1. `Event.enriched_at` field exists in the DB (migration 0024 applied).
2. `Event.enriched_at` is populated whenever the Ollama LLM runs successfully.
3. Event names in the DB are never raw hashtag dumps; title-less events are skipped rather than
   persisted with a garbage fallback.
4. `Event.url` for FB posts is always a real permalink OR a
   `https://www.facebook.com/search/top/?q=<encoded-title>` search link — never a
   `/fbpost/posts/synth_<hash>` URL.
5. `Event.description` (summary) is never an exact copy of `Event.raw_text`; posts whose LLM
   summary is null get `description=""` rather than a 500-char raw-text dump.
6. Phone and email values in the DB are never LLM-fabricated; they must appear literally in the
   raw caption + links text.
7. Title-level content dedup skips posts whose normalized title (or a 10-char prefix thereof)
   already exists in the `facebook_posts` source.
8. `manage.py enrich_fb_posts` re-runs the LLM on un-enriched rows using COALESCE-style logic
   (never overwrites non-null fields).
9. All 97 existing tests continue to pass.

---

## Phase Completion Rules

A phase is NOT complete until:

1. **DB state correct** — manual Django shell query confirms the expected rows/field values.
2. **No test regressions** — `cd apps/backend && ./venv/bin/python manage.py test events` passes.
3. **Manual scrape confirms behavior** — `manage.py scrape facebook_posts` produces expected
   output logs and DB rows for the behaviors introduced in that phase.
4. **User confirmation** — user reviews results before proceeding to the next phase.

Status meanings:
- ⏳ PLANNED — Not started
- CODE DONE — Written but not E2E tested
- TESTING — Currently being tested
- VERIFIED — Tested AND confirmed working
- BLOCKED — Has issues

---

## Scope

### In scope

- `apps/backend/events/models.py` — add `Event.enriched_at` field
- `apps/backend/events/migrations/0024_add_event_enriched_at.py` — new migration
- `apps/backend/events/scrapers/facebook_posts.py` — persistence loop, `_call_llm_structure`,
  `_build_post_prompt`, `_parse_structure_response`
- `apps/backend/events/management/commands/enrich_fb_posts.py` — new file

### Out of scope

- `facebook_events.py`, `base.py`, `proxy_manager.py`, `social_proxy.py` — no changes
- `views.py`, `urls.py`, frontend — no changes
- `save_events` in `base.py` — title dedup happens in the `run()` persistence loop of
  `facebook_posts.py`, not in the shared helper (to avoid affecting other scrapers)
- The smart-scroll and JS constant work already completed in `fb-posts-smart-scroll_PLAN_23-06-26.md`

---

## Background: Current Code State

Before listing changes, here are the exact current signatures and line references:

### `facebook_posts.py` — key sections

- **`_build_post_prompt`** (~line 358): builds the Ollama prompt. Missing an explicit rule that
  hashtag-only / no-readable-event posts should return `is_event=false`.
- **`_parse_structure_response`** (~line 432): parses Ollama JSON response. Does NOT have
  fabrication rejection for phone/email.
- **`_call_llm_structure`** (~line 457): sends prompt to Ollama. Returns `dict | None`.
- **`_post_external_id`** (~line 557): derives stable dedup key from URL; returns the part after
  `facebook.com/` with `/` replaced by `_`.
- **`run()` persistence loop** (~line 1020): the `for raw in raw_by_query...` loop. Currently:
  - Title fallback: `fields.get("title") or (f"{author}: {caption[:80]}" if author else caption[:80])` (line 1063)
  - Description: `fields.get("short_description") or caption[:500]` (line 1080)
  - URL: `post_url` as-is (line 1082) — synth URLs pass through unmodified
  - No title-level dedup check
  - No `enriched_at` assignment

### `models.py` — `Event`

Confirmed fields present: `name`, `description`, `url`, `external_id`, `raw_text`, `post_date`,
`source`, `search_query`. No `enriched_at` field exists. Confirmed: `Organizer` has an
`enriched_at` field (line 200) — use same pattern for `Event`.

### `base.py` — `save_events`

`save_events` calls `Event.objects.update_or_create(source=..., external_id=..., defaults={...})`.
The `defaults` dict is built from `ScrapedEvent` fields. Adding `enriched_at` to `ScrapedEvent`
is **not the right path** — the dataclass is shared across all scrapers. Instead, set
`enriched_at` on the `Event` ORM object directly in `facebook_posts.py`'s persistence loop
after `save_events` returns its `event_ids`.

### Latest migration

The latest applied migration is `0023_add_raw_text_post_date.py`. New migration will be
`0024_add_event_enriched_at.py`.

---

## Phase 1 — Migration: add `Event.enriched_at`

**Status: ⏳ PLANNED**

### What changes

Add `Event.enriched_at = models.DateTimeField(null=True, blank=True)` to `models.py` and create
the corresponding migration.

### Detailed steps

#### Step 1.1 — Add field to `Event` in `models.py`

File: `apps/backend/events/models.py`
Location: after the `post_date` field (~line 130), before the `search_query` FK.

Add:
```
enriched_at = models.DateTimeField(
    null=True, blank=True,
    help_text="Set when the Ollama LLM successfully structured this FB post.",
)
```

Pattern mirrors `Organizer.enriched_at` at line 200 of `models.py`.

Do NOT add `enrichment_source` — that is organizer-specific. Only the timestamp field is needed.

#### Step 1.2 — Generate migration

Run:
```
cd apps/backend && ./venv/bin/python manage.py makemigrations events --name add_event_enriched_at
```

Confirm the generated file is numbered `0024_add_event_enriched_at.py`.
Inspect it to verify it adds exactly one `AddField` for `enriched_at` on `Event`.

#### Step 1.3 — Apply migration

```
cd apps/backend && ./venv/bin/python manage.py migrate
```

#### Step 1.4 — Verify

```python
# Django shell:
from events.models import Event
Event._meta.get_field('enriched_at')   # must not raise
Event.objects.filter(enriched_at__isnull=True).count()  # returns total fb_posts rows (all null initially)
```

Run test suite:
```
cd apps/backend && ./venv/bin/python manage.py test events
```

All 97 tests must pass.

### Phase 1 acceptance criteria

- `Event._meta.get_field('enriched_at')` does not raise `FieldDoesNotExist`.
- `0024_add_event_enriched_at.py` exists in `migrations/`.
- All 97 tests pass.
- User confirms migration applied on their Neon DB.

---

## Phase 2 — Scraper Persistence Fixes

**Status: ⏳ PLANNED**

Depends on: Phase 1 complete (migration applied, `Event.enriched_at` accessible).

### What changes (3 sub-items)

**2A — Title-skip for title-less posts** (fixes hashtag-dump names)

**2B — Synth URL → search-link fallback** (fixes fake links)

**2C — Content dedup by normalized title** (reference port from `events-posts.js:146-171`)

**2D — Set `enriched_at` after persistence**

All changes are inside the `run()` method's persistence loop in `facebook_posts.py`, roughly
lines 1020–1130.

### 2A — Title-skip for title-less posts

#### Motivation

When the LLM returns `is_event=true` but `title=null` (common with hashtag-heavy captions), the
current code falls back to `f"{author}: {caption[:80]}"` as `name` and `caption[:500]` as
`description`. This produces:
- Name: `"Some Page: #Cebu #Events #Sports 2026 #Tri..."`
- Description: identical to `raw_text` (the first 500 chars)

Both outputs are useless in Sheets.

#### Rule

**If** `structured is not None` (LLM ran and is_event=true) **and** `fields.get("title")` is
falsy after `_coerce_str`, then **skip** the post (do not append to `scraped_events`).

Rationale: a real event post always has enough readable prose for the LLM to extract a title.
If the LLM returned `is_event=true` but could not extract a title, the post was likely a
hashtag dump that slipped past `is_event=false` — skip it rather than pollute the DB.

**If** `structured is None` (Ollama offline — fallback path), the title fallback is still
acceptable since the post is persisted as a raw/unverified record. The offline fallback title
`f"{author}: {caption[:80]}"` remains.

#### Changes in `run()` persistence loop

After the `if structured is not None and not structured["is_event"]: continue` block (current
line ~1042), add:

```python
# Skip if LLM ran but could not extract a readable title (hashtag-dump guard).
if structured is not None and not fields.get("title"):
    logger.debug("[%s] SKIP no-title (hashtag dump?): %s", self.source, post_url[:60])
    continue
```

For `description` (the summary), change the current assignment:
```python
# Current: fields.get("short_description") or caption[:500]
# New:
description = fields.get("short_description") or ""
```
This eliminates `description == raw_text` for all LLM-processed posts. The `raw_text` column
already holds the full caption independently.

#### Impact on title assignment

The title line (current ~1063) stays as-is:
```python
title = fields.get("title") or (f"{author}: {caption[:80]}" if author else caption[:80])
```
Because the new skip guard fires BEFORE this line when `structured is not None` and title is
null, the fallback only runs for the offline/None case.

### 2B — Synth URL → search-link fallback

#### Motivation

`_EXTRACT_POSTS_JS` emits `https://www.facebook.com/fbpost/posts/synth_<hash>` when no real
permalink anchor is found. The `external_id` derived from this URL is a stable dedup key (the
synth hash is deterministic from the caption prefix), so re-scrapes of the same post still
deduplicate correctly. The problem is only in `Event.url` — the stored URL is not clickable.

#### Rule

Compute the `external_id` from `post_url` as now. Then before building `ScrapedEvent`, check:

```python
save_url = post_url
if "/fbpost/posts/synth_" in post_url:
    # Build a search-link fallback using the clean title (or first non-hashtag line of caption).
    _query_text = fields.get("title") or _first_readable_line(caption)
    if _query_text:
        save_url = (
            "https://www.facebook.com/search/top/?q="
            + urllib.parse.quote(_query_text.strip(), safe="")
        )
    # external_id still derived from post_url (synth) — not from save_url
```

The `external_id` assignment uses `_post_external_id(post_url)` (unchanged — dedup key
continues to be the synth URL-derived string).
`ScrapedEvent.url` is set to `save_url` (real URL or search-link; never the synth string).

#### `_first_readable_line` helper

Add a module-level helper in `facebook_posts.py`:

```
def _first_readable_line(text: str) -> str | None:
    """Return the first line of `text` that is not purely hashtags/whitespace."""
    for line in (text or "").splitlines():
        stripped = line.strip()
        # Skip blank lines and lines that are only hashtags/mentions
        clean = re.sub(r'[#@]\S+', '', stripped).strip()
        if len(clean) >= 10:
            return stripped[:120]
    return None
```

### 2C — Content dedup by normalized title

#### Motivation

Reference `events-posts.js:146-171` runs a pre-insert SQL query against `facebook.posts` rows
with two matching conditions:
- Exact normalized title match
- Prefix match (if normalized title >= 10 chars, one title starts the other)

Normalization: lowercase, strip non-alphanumeric non-space characters, trim.

#### Implementation strategy

Do this in Python inside the persistence loop (before appending to `scraped_events`), using an
ORM query. Using Python rather than a raw SQL DB call avoids complexity and keeps it within the
existing ORM-outside-Playwright pattern.

**Normalization function** (add as module-level helper):

```python
def _normalize_title_for_dedup(title: str) -> str:
    """Lowercase, strip non-alphanumeric-space chars, collapse whitespace."""
    import re
    t = title.lower()
    t = re.sub(r'[^a-z0-9 ]+', '', t)
    return re.sub(r'\s+', ' ', t).strip()
```

**Dedup query** (inside the persistence loop, after title is computed):

```python
norm_title = _normalize_title_for_dedup(title)
if len(norm_title) >= 3:  # skip check for extremely short normalized titles
    # Check 1: exact match
    exact_dup = Event.objects.filter(
        source=self.source,
    ).extra(
        where=["regexp_replace(lower(trim(name)), '[^a-z0-9 ]+', '', 'g') = %s"],
        params=[norm_title],
    ).exists()

    # Check 2: prefix match (one is a prefix of the other, min 10 chars)
    prefix_dup = False
    if not exact_dup and len(norm_title) >= 10:
        prefix_dup = Event.objects.filter(
            source=self.source,
        ).extra(
            where=[
                "regexp_replace(lower(trim(name)), '[^a-z0-9 ]+', '', 'g') LIKE %s"
                " OR %s LIKE regexp_replace(lower(trim(name)), '[^a-z0-9 ]+', '', 'g') || ' %%'"
            ],
            params=[norm_title + " %", norm_title],
        ).exists()

    if exact_dup or prefix_dup:
        logger.debug("[%s] DUP (content) title='%s': %s", self.source, title[:60], post_url[:60])
        continue
```

**Note on `.extra()`**: Django's `.extra(where=...)` with raw SQL is acceptable here because:
(a) this is the scraper layer, not a user-facing view; (b) the normalization expression mirrors
the reference SQL exactly (PostgreSQL `regexp_replace`); (c) the params are bound, not interpolated.
If the project later adds a Django ORM annotation for normalized title, migrate at that time.

### 2D — Set `enriched_at` after persistence

After `save_events` returns and `event_ids` are known, stamp `enriched_at` for newly-created
rows where the LLM ran:

In the persistence loop, track which posts had the LLM run successfully:
- Add a local set `enriched_event_urls: set[str]` initialized before the inner `for raw` loop.
- After `structured = _call_llm_structure(...)`, if `structured is not None`, add `external_id`
  to `enriched_event_urls`.

After `result = save_events(self.source, scraped_events)`:
```python
# Stamp enriched_at for rows where the LLM ran (structured was not None).
# Only update rows that were just created or updated in this batch.
if enriched_event_urls and result.get("event_ids"):
    Event.objects.filter(
        pk__in=result["event_ids"],
        external_id__in=enriched_event_urls,
        enriched_at__isnull=True,  # COALESCE-style: never overwrite an existing stamp
    ).update(enriched_at=timezone.now())
```

Using `enriched_at__isnull=True` ensures a row's first enrichment timestamp is preserved
across re-scrapes (matches the reference's COALESCE pattern).

### Phase 2 implementation checklist

- [ ] **Step 2.1 — Add `_first_readable_line` helper** before the `FacebookPostsScraper` class
  in `facebook_posts.py`.

- [ ] **Step 2.2 — Add `_normalize_title_for_dedup` helper** before the `FacebookPostsScraper`
  class in `facebook_posts.py`.

- [ ] **Step 2.3 — Add no-title skip guard** in `run()` after the `is_event=false` skip block
  (~line 1042). Condition: `if structured is not None and not fields.get("title"): continue`.

- [ ] **Step 2.4 — Change `description` assignment** from `fields.get("short_description") or caption[:500]`
  to `fields.get("short_description") or ""`.

- [ ] **Step 2.5 — Add synth-URL → search-link replacement** block before `ScrapedEvent`
  construction. Introduce `save_url` variable; `ScrapedEvent.url` = `save_url`.
  Verify `external_id` still uses `_post_external_id(post_url)` (not `save_url`).

- [ ] **Step 2.6 — Add content dedup query** in `run()` after title is computed, before
  appending to `scraped_events`.

- [ ] **Step 2.7 — Add `enriched_event_urls` tracking set** before the inner `for raw` loop.
  Populate it when `structured is not None`.

- [ ] **Step 2.8 — Add `enriched_at` bulk-update** after `save_events` call for each query.

- [ ] **Step 2.9 — Run tests**:
  ```
  cd apps/backend && ./venv/bin/python manage.py test events
  ```
  All 97 must pass.

- [ ] **Step 2.10 — Manual scrape + DB inspection** (see Verification Evidence section).

### Phase 2 acceptance criteria

1. After a scrape, no `Event` row with `source='facebook_posts'` has `name` matching
   `r'^[^:]+:\s*#'` (hashtag-dump fallback pattern).
2. No `Event.url` contains `/fbpost/posts/synth_` — synth URLs are only in `external_id`.
3. `Event.description` does not equal `Event.raw_text` for any `facebook_posts` row.
4. `Event.enriched_at` is set for rows where the LLM ran.
5. All 97 tests pass.

---

## Phase 3 — LLM Fabrication Rejection + Prompt Tightening

**Status: ⏳ PLANNED**

Depends on: Phase 2 complete.

### What changes

**3A — Ground-truth fabrication rejection for phone/email** (port from `llm.js:200-253`)

**3B — Tighten `_build_post_prompt` for hashtag-only posts**

Both changes are inside functions that are already present in `facebook_posts.py`.

### 3A — Fabrication rejection

#### Reference implementation (`llm.js:200-253`)

```javascript
function phoneFoundInText(phone, sourceText) {
  const digits = phone.replace(/\D/g, '');
  if (digits.length < 7) return false;
  const sourceDigits = sourceText.replace(/\D/g, '');
  return sourceDigits.includes(digits);
}

function emailFoundInText(email, sourceText) {
  return sourceText.toLowerCase().includes(email.toLowerCase());
}

// Applied inside structureFBPost after coerceFBPost:
const allText = [rawCaption, ...(rawLinks || [])].join(' ');
if (result.organizer_phone && !phoneFoundInText(result.organizer_phone, allText)) {
  result.organizer_phone = null;
}
if (result.organizer_email && !emailFoundInText(result.organizer_email, allText)) {
  result.organizer_email = null;
}
```

#### Python port

Add two module-level helpers to `facebook_posts.py`:

```python
def _phone_found_in_text(phone: str, source_text: str) -> bool:
    """Return True only if phone's digit-run appears verbatim in source_text."""
    digits = re.sub(r'\D', '', phone or '')
    if len(digits) < 7:
        return False
    source_digits = re.sub(r'\D', '', source_text or '')
    return digits in source_digits

def _email_found_in_text(email: str, source_text: str) -> bool:
    """Return True only if email appears literally (case-insensitive) in source_text."""
    return bool(email) and bool(source_text) and (email.lower() in source_text.lower())
```

Apply them in `_parse_structure_response` (or equivalently, in `_call_llm_structure` after
parsing, mirroring the reference). Since `_parse_structure_response` does not receive `raw_links`
or `caption` as arguments, apply the rejection in `_call_llm_structure` after calling
`_parse_structure_response`:

```python
# Inside _call_llm_structure, after: result = _parse_structure_response(text)
if result is not None:
    all_text = raw_caption + " " + " ".join(raw_links or [])
    if result.get("organizer_phone") and not _phone_found_in_text(result["organizer_phone"], all_text):
        logger.warning(
            "[facebook_posts] fabricated phone rejected: %s",
            result["organizer_phone"],
        )
        result["organizer_phone"] = None
    if result.get("organizer_email") and not _email_found_in_text(result["organizer_email"], all_text):
        logger.warning(
            "[facebook_posts] fabricated email rejected: %s",
            result["organizer_email"],
        )
        result["organizer_email"] = None
```

This is the correct injection point because `_call_llm_structure` already receives `raw_caption`
and `raw_links` as arguments (line 458 signature).

### 3B — Prompt tightening for hashtag-only posts

Modify `_build_post_prompt` (currently ~line 358) to add an explicit rule:

After the existing "Set `is_event` to false if the post is:" bullet list, insert:

```
"  - A post whose entire text is hashtags, emojis, or mentions with no readable event announcement",
"  - A post that has a readable title or description less than 20 characters long",
```

Also after the existing `is_event=true` condition line, insert:

```
"IMPORTANT: if you cannot extract a meaningful event title (not just hashtags) from the post,",
"  set is_event to false rather than inventing a title.",
```

This reduces false-positive `is_event=true` returns on hashtag dumps, decreasing the frequency
of the no-title skip guard being needed (defense in depth — the skip guard remains as the final
safety net, but ideally the LLM returns `is_event=false` before we even reach it).

### Phase 3 implementation checklist

- [ ] **Step 3.1 — Add `_phone_found_in_text` helper** before the `FacebookPostsScraper` class.

- [ ] **Step 3.2 — Add `_email_found_in_text` helper** beside `_phone_found_in_text`.

- [ ] **Step 3.3 — Add fabrication rejection block** inside `_call_llm_structure`, after
  `result = _parse_structure_response(text)` (currently ~line 493). Block uses `raw_caption`
  and `raw_links` already in scope.

- [ ] **Step 3.4 — Add hashtag-only prompt rules** to `_build_post_prompt`. Insert two new
  bullet points in the `is_event=false` list. Insert one `IMPORTANT:` paragraph after the
  `is_event=true` condition.

- [ ] **Step 3.5 — Run tests**:
  ```
  cd apps/backend && ./venv/bin/python manage.py test events
  ```
  All 97 must pass.

- [ ] **Step 3.6 — LLM smoke test** (see Verification Evidence).

### Phase 3 acceptance criteria

1. Feed a caption that is `"#Cebu #Events #Sports #Running"` to a local Ollama call — model
   returns `is_event=false` (due to new prompt rule).
2. For a post where the LLM returns a fabricated phone/email not in the caption, the
   `_phone_found_in_text` / `_email_found_in_text` rejection fires and logs a warning.
3. `Event.organizer` / Organizer email/phone fields in DB do not contain values absent from
   `Event.raw_text`.
4. All 97 tests pass.

---

## Phase 4 — `enrich_fb_posts` Management Command

**Status: ⏳ PLANNED**

Depends on: Phase 1 (migration) and Phase 3 (fabrication rejection in `_call_llm_structure`).

### What changes

New file: `apps/backend/events/management/commands/enrich_fb_posts.py`

Mirrors `events-posts.js:222-291` (`/reprocess` route) as a Django management command.

### Behavior

1. Query `Event.objects.filter(source='facebook_posts', enriched_at__isnull=True).order_by('-scraped_at')`.
2. Limit to `--limit` (default 200) rows per run.
3. For each row:
   a. Reconstruct `raw_caption` from `raw_text` (primary); fall back to stripping the
      `author: ` prefix from `name` if `raw_text` is empty.
   b. Reconstruct `author_name` from `organizer` field.
   c. Reconstruct `timestamp` from `scraped_at` isoformat (or `post_date` if available).
   d. Call `_call_llm_structure(raw_caption, author_name, timestamp, raw_links=[])`.
   e. If `structured is None` or `structured.is_event is False`: skip, increment `skipped`.
   f. If `structured` is valid: apply COALESCE-style update — only write fields that are
      currently null/empty. Always overwrite `name` (title) and set `enriched_at=timezone.now()`.

4. Print summary: `total / updated / skipped / failed`.

#### COALESCE-style update logic

```python
updates = {"enriched_at": timezone.now()}
# title: always overwrite (may have been a garbage fallback)
if structured.get("title"):
    updates["name"] = structured["title"][:300]
# description: only fill if currently empty
if not event.description and structured.get("short_description"):
    updates["description"] = structured["short_description"]
# starts_at: only fill if currently null
if event.starts_at is None and structured.get("start_datetime"):
    from events.scrapers.facebook_posts import _parse_post_date
    dt = _parse_post_date(structured["start_datetime"])
    if dt:
        updates["starts_at"] = dt
# organizer: only fill if currently empty
if not event.organizer and structured.get("organizer_name"):
    updates["organizer"] = structured["organizer_name"][:255]
```

`Event.objects.filter(pk=event.pk).update(**updates)`

Note: `url` is NOT updated by the enrichment command — the URL was set at scrape time and
Phase 2 already fixed synth URLs going forward. Old synth URLs in the DB can be identified
via `Event.objects.filter(source='facebook_posts', url__contains='/fbpost/posts/synth_')` and
cleaned up separately if needed (out of scope for this plan).

#### Command signature

```
manage.py enrich_fb_posts [--limit N] [--dry-run]
```

- `--limit N` (default 200): max rows per invocation (mirrors `MAX_REPROCESS=200`).
- `--dry-run`: log what would be updated without writing to DB.

### Phase 4 implementation checklist

- [ ] **Step 4.1 — Create `enrich_fb_posts.py`** at
  `apps/backend/events/management/commands/enrich_fb_posts.py`.
  - Extend `BaseCommand`.
  - `add_arguments`: `--limit` (int, default=200) and `--dry-run` (store_true).
  - `handle`: main loop with query, per-row logic, COALESCE update, summary output.

- [ ] **Step 4.2 — Import `_call_llm_structure` and `_parse_post_date`** from
  `events.scrapers.facebook_posts` inside the command (avoid circular imports at module level).

- [ ] **Step 4.3 — Dry-run mode**: when `--dry-run` is set, log "WOULD UPDATE" instead of
  calling `.update()`.

- [ ] **Step 4.4 — Run tests**:
  ```
  cd apps/backend && ./venv/bin/python manage.py test events
  ```
  All 97 must pass.

- [ ] **Step 4.5 — Smoke-test the command**:
  ```
  cd apps/backend && ./venv/bin/python manage.py enrich_fb_posts --dry-run --limit 5
  ```
  Should log "WOULD UPDATE" for up to 5 rows; no DB writes.

- [ ] **Step 4.6 — Live run on un-enriched rows**:
  ```
  cd apps/backend && ./venv/bin/python manage.py enrich_fb_posts --limit 50
  ```
  Inspect result rows in Django shell:
  ```python
  from events.models import Event
  qs = Event.objects.filter(source='facebook_posts', enriched_at__isnull=False)
  print(qs.count(), "enriched")
  sample = qs.first()
  print(sample.name, sample.enriched_at, sample.description[:80])
  ```

### Phase 4 acceptance criteria

1. `manage.py enrich_fb_posts --dry-run --limit 5` runs without error and logs "WOULD UPDATE"
   for rows with `enriched_at IS NULL`.
2. After a live run, `Event.objects.filter(source='facebook_posts', enriched_at__isnull=False).count()`
   increases.
3. Re-running the command does NOT overwrite already-enriched rows (because they are excluded by
   `enriched_at__isnull=True` filter and by COALESCE-style per-field guards).
4. `name` for updated rows does not contain hashtag-dump patterns.
5. All 97 tests pass.

---

## Touchpoints

| Surface | File | Change |
|---------|------|--------|
| `Event` model | `apps/backend/events/models.py` | Add `enriched_at = DateTimeField(null=True, blank=True)` |
| Migration 0024 | `apps/backend/events/migrations/0024_add_event_enriched_at.py` | New — adds `enriched_at` to `Event` |
| `_build_post_prompt` | `facebook_posts.py` ~line 358 | Add hashtag-only `is_event=false` prompt rules |
| `_parse_structure_response` | `facebook_posts.py` ~line 432 | No change (fabrication rejection moved to caller) |
| `_call_llm_structure` | `facebook_posts.py` ~line 457 | Add fabrication rejection after parsing |
| `run()` persistence loop | `facebook_posts.py` ~lines 1020-1130 | Add no-title skip, description fix, synth-URL fix, content dedup, `enriched_at` stamping |
| `_first_readable_line` | `facebook_posts.py` | New module-level helper |
| `_normalize_title_for_dedup` | `facebook_posts.py` | New module-level helper |
| `_phone_found_in_text` | `facebook_posts.py` | New module-level helper |
| `_email_found_in_text` | `facebook_posts.py` | New module-level helper |
| `enrich_fb_posts` command | `apps/backend/events/management/commands/enrich_fb_posts.py` | New file |

---

## Public Contracts

- **`Event.enriched_at`** — new nullable DateTimeField. Exposed in `Event.__str__` repr only
  through admin; not exposed by any API endpoint currently. If `views.py` `api_events` is later
  updated to include this field, it is safe (null-able, ISO format serializable).
- **`_call_llm_structure` signature** — unchanged. Internal behavior changes (fabrication
  rejection) are transparent to callers.
- **`run()` return dict** — unchanged: `{source, created, updated}`.
- **`ScrapedEvent` dataclass** — no changes. `enriched_at` is not added to the dataclass;
  it is set via a separate ORM `.update()` after `save_events` returns.
- **`enrich_fb_posts` command** — new public surface; `--dry-run` flag for safe pre-inspection.
- **DB dedup invariant** — the `unique_source_external_id` constraint is unchanged. Synth
  `external_id` strings continue to function as dedup keys. Only `Event.url` changes (not the
  dedup field).

---

## Blast Radius

### Files modified
- `apps/backend/events/models.py` — additive only (new field)
- `apps/backend/events/migrations/0024_add_event_enriched_at.py` — new file
- `apps/backend/events/scrapers/facebook_posts.py` — behavior changes inside existing functions
- `apps/backend/events/management/commands/enrich_fb_posts.py` — new file

### Files NOT modified
- `base.py`, `save_events` — no changes
- `views.py`, `urls.py` — no changes
- `facebook_events.py` — no changes
- Frontend — no changes
- `tests.py` — no new tests written (manual verification plan below), but all 97 existing tests
  must continue to pass

### Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| No-title skip guard drops legitimately title-less events | Low | Medium | Guard only fires when `structured is not None` (LLM ran); offline-fallback path unaffected |
| Synth-URL search-link is less useful than the synth URL itself | Low | Low | Synth URLs were already not clickable; search-link at least navigates somewhere relevant |
| Content dedup `.extra()` query with `regexp_replace` slow on large tables | Low | Low | Filter by `source='facebook_posts'` first; add DB index on `(source, name)` only if measured slow |
| `enrich_fb_posts` accidentally overwrites enriched rows | Low | Medium | `enriched_at__isnull=True` filter in query; COALESCE guards per field; `--dry-run` available |
| Fabrication rejection too aggressive (valid numbers/emails rejected) | Low | Low | Phone check is digit-substring match (handles spaces/dashes); email check is case-insensitive substring |
| Migration 0024 conflicts with a pending migration | None | Medium | Confirm latest applied = 0023 before running `makemigrations` |

---

## Verification Evidence

After all phases complete, ALL of the following must be true:

### Automated

1. `cd apps/backend && ./venv/bin/python manage.py test events` — 97 tests pass (after each phase).
2. `cd apps/backend && ./venv/bin/python manage.py makemigrations --check --dry-run` — exits 0
   (no pending migrations after migration applied).

### LLM smoke test (Phase 3 gate)

```bash
curl -s -X POST http://localhost:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5:7b-instruct","prompt":"You are an event-detection engine.\nSet \"is_event\" to false if the post is only hashtags.\nPost text:\n\"\"\"\n#Cebu #Events #Sports #Running #2026\n\"\"\"\nRespond with ONLY a JSON object with is_event.","stream":false}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['response'])"
```

Expected: response contains `"is_event": false`.

### DB inspection (after Phase 2 scrape)

```python
from django.db.models import Q
from events.models import Event

# 1. No hashtag-dump names
hashtag_dump = Event.objects.filter(
    source='facebook_posts',
    name__regex=r'^[^:]+:\s*#'
)
assert hashtag_dump.count() == 0, f"Found {hashtag_dump.count()} hashtag-dump names"

# 2. No synth URLs in Event.url
synth_urls = Event.objects.filter(
    source='facebook_posts',
    url__contains='/fbpost/posts/synth_'
)
assert synth_urls.count() == 0, f"Found {synth_urls.count()} synth URLs in Event.url"

# 3. description != raw_text (no raw-text duplicates)
from django.db.models import F
desc_eq_raw = Event.objects.filter(
    source='facebook_posts',
).exclude(
    raw_text=''
).filter(description=F('raw_text'))
assert desc_eq_raw.count() == 0, f"Found {desc_eq_raw.count()} rows where description=raw_text"

# 4. enriched_at set for recent scrape rows
enriched = Event.objects.filter(source='facebook_posts', enriched_at__isnull=False)
print(f"Enriched rows: {enriched.count()}")
```

### Duplicate dedup invariant

```python
from django.db.models import Count
dupes = Event.objects.values('source', 'external_id').annotate(
    c=Count('id')
).filter(c__gt=1, source='facebook_posts')
assert dupes.count() == 0, f"Duplicate external_ids found: {list(dupes)}"
```

### n8n / Sheets column check

After a scrape with the new code, verify in n8n webhook payload or Sheets output:
- `name` column contains readable event titles (no `PageName: #hashtag...` entries)
- `url` column contains `facebook.com/search/top/?q=` links (not `/fbpost/posts/synth_`) or real
  permalinks
- `summary` column is not a copy of `raw_text` column
- `enriched_at` column is set (non-null) for newly scraped rows

---

## Implementation Checklist

Full ordered sequence across all phases:

### Phase 1 — Migration

- [ ] 1.1 Add `enriched_at = models.DateTimeField(null=True, blank=True, ...)` to `Event` in `models.py` after `post_date` field
- [ ] 1.2 Run `makemigrations events --name add_event_enriched_at` and confirm file is `0024_...py`
- [ ] 1.3 Run `migrate` — apply to Neon DB
- [ ] 1.4 Verify: `Event._meta.get_field('enriched_at')` does not raise; run test suite (97 pass)

### Phase 2 — Persistence fixes

- [ ] 2.1 Add `_first_readable_line(text)` module-level helper in `facebook_posts.py`
- [ ] 2.2 Add `_normalize_title_for_dedup(title)` module-level helper in `facebook_posts.py`
- [ ] 2.3 Add no-title skip guard in `run()` after `is_event=false` skip block
- [ ] 2.4 Change `description` assignment from `or caption[:500]` to `or ""`
- [ ] 2.5 Add `save_url` synth-URL detection + search-link substitution before `ScrapedEvent` construction; ensure `external_id` still uses `_post_external_id(post_url)`
- [ ] 2.6 Add content dedup query (normalized title exact + prefix match) after `title` is computed; `continue` on duplicate
- [ ] 2.7 Add `enriched_event_urls` set before inner `for raw` loop; populate when `structured is not None`
- [ ] 2.8 Add `enriched_at` bulk-update after `save_events` for each query
- [ ] 2.9 Run test suite (97 must pass)
- [ ] 2.10 Manual scrape + DB inspection (per Verification Evidence checks 1–4)

### Phase 3 — LLM fabrication rejection + prompt tightening

- [ ] 3.1 Add `_phone_found_in_text(phone, source_text)` module-level helper
- [ ] 3.2 Add `_email_found_in_text(email, source_text)` module-level helper
- [ ] 3.3 Add fabrication rejection block inside `_call_llm_structure` after `_parse_structure_response` call; use `raw_caption` and `raw_links` from function scope
- [ ] 3.4 Add two hashtag-only bullet points to `_build_post_prompt` `is_event=false` list; add one `IMPORTANT:` paragraph after `is_event=true` line
- [ ] 3.5 Run test suite (97 must pass)
- [ ] 3.6 LLM smoke test (curl to Ollama with hashtag-only caption; confirm `is_event=false`)

### Phase 4 — `enrich_fb_posts` management command

- [ ] 4.1 Create `apps/backend/events/management/commands/enrich_fb_posts.py` with `BaseCommand` subclass, `--limit` and `--dry-run` arguments, and main loop
- [ ] 4.2 Import `_call_llm_structure` and `_parse_post_date` from `events.scrapers.facebook_posts` inside `handle()` (not at module level)
- [ ] 4.3 Implement COALESCE-style per-field update; always write `name` (title) and `enriched_at`; only fill other fields if currently null/empty
- [ ] 4.4 Run test suite (97 must pass)
- [ ] 4.5 Dry-run smoke test: `manage.py enrich_fb_posts --dry-run --limit 5`
- [ ] 4.6 Live run: `manage.py enrich_fb_posts --limit 50`; verify enriched count increased and names are clean

---

## Dependencies

| Dependency | Type | Notes |
|-----------|------|-------|
| Phase 1 before Phase 2 | Hard | Phase 2 sets `enriched_at` — field must exist in DB |
| Phase 1 before Phase 4 | Hard | Phase 4 queries `enriched_at__isnull=True` |
| Phase 3 before Phase 4 | Soft | Phase 4 calls `_call_llm_structure`; fabrication rejection in Phase 3 makes enrichment output cleaner. Can be reversed if needed. |
| Phase 2 and Phase 3 | Independent | Can be done in either order; plan sequences 2 then 3 for logical grouping |
| `fb-posts-smart-scroll_PLAN_23-06-26.md` | Prerequisite | Smart scroll and JS constant work should already be complete or in-progress before this plan's execute phase begins |

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| No-title skip causes too many posts to be dropped | Monitor `SKIP no-title` log lines; if rate is too high, relax by also skipping only when caption is >= 80% hashtags (add `_is_hashtag_heavy(caption)` helper in a follow-up) |
| Content dedup `.extra()` query uses PostgreSQL `regexp_replace` — not portable | This codebase uses Neon PostgreSQL exclusively; no SQLite compatibility needed |
| `enrich_fb_posts` called concurrently with a live scrape run | Both use ORM-level upserts; `enriched_at__isnull=True` filter and `COALESCE` guards prevent race overwrite. Consider adding a `select_for_update(skip_locked=True)` on the enrich query if concurrent execution is expected |
| `save_events` in `base.py` may not return `event_ids` for all scrapers | Confirmed: `save_events` returns `{"created", "updated", "event_ids"}` — `event_ids` is a list of PKs for created/updated rows |

---

## Resume and Execution Handoff

**Execute agent must:**

1. Confirm that `fb-posts-smart-scroll_PLAN_23-06-26.md` has been implemented (or is not
   blocking — the plans are independent but the smart-scroll plan touches the same file).
2. Execute phases strictly in order: 1 → 2 → 3 → 4.
3. Run the 97-test suite after each phase before proceeding.
4. Read `apps/backend/events/scrapers/facebook_posts.py` in full before making any changes.
5. Read `apps/backend/events/models.py` lines 83-165 before Phase 1.
6. After Phase 2 step 2.5, confirm via grep that no `ScrapedEvent(url=post_url)` assignment
   remains — all `ScrapedEvent` constructions must use `url=save_url`.
7. After Phase 4 step 4.1, confirm via import test:
   ```
   cd apps/backend && ./venv/bin/python manage.py help enrich_fb_posts
   ```

**Selected plan file for EXECUTE:** `process/general-plans/active/fb-posts-reference-parity_PLAN_24-06-26.md`

**Supporting plan file (read for context, do not re-implement):**
`process/general-plans/active/fb-posts-smart-scroll_PLAN_23-06-26.md`

**Validate plan artifact before execute:**
```
node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs process/general-plans/active/fb-posts-reference-parity_PLAN_24-06-26.md
```

---

## Cursor + RIPER-5 Guidance

- **Cursor Plan mode:** Import the Implementation Checklist above. Work through steps 1.1–4.6 in
  order, using the phase acceptance criteria as go/no-go gates.
- **RIPER-5:** This plan is the output of PLAN mode. Say `ENTER EXECUTE MODE` to begin.
- If a test fails after any step, stop and diagnose before continuing to the next step.
- After Phase 2 step 2.10 (manual scrape), pause and confirm with the user before proceeding to
  Phase 3.
- After Phase 4 step 4.6 (live enrich run), pause and confirm results with the user.
- **After step 4.6, stop and confirm user says "it works" before marking plan complete.**
