# Venue Extraction Noise Fix

**Date:** 23-06-26
**Complexity:** SIMPLE (single file, JS string changes only)

---

## Root Cause

`_EXTRACT_SEARCH_JS` in `facebook_events.py` collects card text via `getTextLines(root)`, which
queries all `span`/`div` descendants of a `findCardRoot` result. `findCardRoot` walks up the DOM
until it finds an ancestor taller than 80 px — often a large container that shares the DOM
subtree with modal overlays or ad labels rendered nearby.

`pickLineAfterDate(lines, 1)` takes the 2nd non-noise line after a date marker and assigns it as
`venue_name`. It has **no domain constraint** on what a venue looks like, so any string that
passes `isNoise()` qualifies.

Two confirmed bleed-in sources:

| Bad value | Source | Why it slips through |
|---|---|---|
| `"Forgotten account?"` | Facebook login modal link | Not in `UI_CHROME_SET`; `isNoise()` passes |
| `"Ad Choices"` | Sponsored/ad event label | Not in `UI_CHROME_SET`; `isNoise()` passes |

---

## Fix Strategy

Three layered changes, all in `_EXTRACT_SEARCH_JS`:

### Layer 1 — Expand `UI_CHROME_SET`
Add every Facebook UI string that has been observed as false positives:
```js
const UI_CHROME_SET = new Set([
  'events','home','watch','marketplace','menu','notifications',
  'your events','facebook','log in','sign up','create account','anyone',
  // --- add ---
  'forgotten account?','ad choices','ad choices ·','sponsored','create new account',
  'see more','see less','view more','learn more','privacy','terms','cookies',
]);
```

### Layer 2 — Add a venue-specific validation guard
`pickLineAfterDate` is used for both `title` (n=0) and `venue_name` (n=1). Introduce a
`pickVenueLine(lines)` function that applies additional constraints on top of `isNoise`:

```js
function pickVenueLine(lines) {
    // Venue must look like a place name: no trailing "?", no all-caps labels,
    // no "·" separator chars (ad/metadata markers), not starting with a verb phrase.
    function looksLikeVenue(t) {
        if (t.endsWith('?')) return false;
        if (/·/.test(t)) return false;
        if (/^(ad|sponsored|suggested|people you may know)/i.test(t)) return false;
        return true;
    }
    let passedDate = false, count = 0;
    for (const t of lines) {
        if (DATE_WORD_RE.test(t)) { passedDate = true; continue; }
        if (!passedDate) continue;
        if (isNoise(t) || !looksLikeVenue(t)) continue;
        if (count === 1) return t;
        count++;
    }
    // fallback without requiring a date
    count = 0;
    for (const t of lines) {
        if (isNoise(t) || !looksLikeVenue(t)) continue;
        if (count === 1) return t;
        count++;
    }
    return null;
}
```

Replace the `venue_name` line:
```js
// before
venue_name: pickLineAfterDate(lines, 1) || null,
// after
venue_name: pickVenueLine(lines) || null,
```

### Layer 3 — Skip ad/sponsored cards entirely
If the card's lines contain an ad marker, skip the card rather than extracting bad data:
```js
const isAdCard = lines.some(t =>
    /^(ad|sponsored)$/i.test(t) || t.toLowerCase() === 'ad choices'
);
if (isAdCard) continue;
```
Insert this check immediately after `const lines = getTextLines(root)`.

---

## Touchpoints

| File | Change |
|---|---|
| `apps/backend/events/scrapers/facebook_events.py` | `_EXTRACT_SEARCH_JS` only — `UI_CHROME_SET`, new `pickVenueLine`, ad-card skip |

No model changes, no migrations, no API changes, no frontend changes.

---

## Blast Radius

- **Narrow**: single JS string inside one scraper method
- `title` extraction (`pickLineAfterDate(lines, 0)`) is unchanged
- `organizer_name` extraction is unchanged
- `city_location` extraction in `_EXTRACT_DETAIL_JS` is separate and unchanged
- Risk: expanding `UI_CHROME_SET` could suppress a venue that happens to share a name — mitigated because none of the new strings are plausible venue names

---

## Implementation Checklist

- [ ] Open `apps/backend/events/scrapers/facebook_events.py`, locate `_EXTRACT_SEARCH_JS`
- [ ] Layer 1: extend `UI_CHROME_SET` with the additional strings listed above
- [ ] Layer 2: add `pickVenueLine(lines)` function below `pickLineAfterDate`; replace `venue_name` assignment
- [ ] Layer 3: add `isAdCard` check immediately after `const lines = getTextLines(root)`, before `respondent_count`

---

## Verification Evidence

Manual spot-check by running the scraper (no automated tests cover JS extraction):

```bash
# Start a limited run and observe the log lines
cd apps/backend
python manage.py run_scraper_job --run-id <id>  # or trigger via UI

# In the log, look for venue= columns:
# GOOD:  venue=SM MOA
# GOOD:  venue=Pasay City, Philippines
# GOOD:  venue=—          (null is fine when venue is genuinely unknown)
# BAD:   venue=Forgotten account?
# BAD:   venue=Ad Choices
```

No regression: title and organizer columns should be unchanged across the same events.

---

## Resume Handoff

**Plan path:** `process/general-plans/active/venue-extraction-noise_PLAN_23-06-26.md`

Single file, three self-contained layers. Implement in order 1 → 2 → 3. Each layer is
independently correct — if Layer 3 causes unexpected card drops, it can be reverted without
affecting Layers 1 and 2.
