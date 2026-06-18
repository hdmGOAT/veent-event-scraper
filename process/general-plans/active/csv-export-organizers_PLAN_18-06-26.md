# CSV Export — Organizers Page
**Plan type:** SIMPLE  
**Date:** 2026-06-18  
**Status:** ACTIVE

---

## Overview

Add an "Export CSV" button to the organizers list page (`/organizers/`) that downloads a
flattened, human-readable CSV of all organizers matching the current filter state (`q`,
`status`). The export is full (no pagination cap). No new Python or JS dependencies.

---

## Goals

1. Backend: new Django view `api_organizers_export` at `GET /api/organizers/export/` that
   streams a CSV response for all matching organizers.
2. Frontend: "Export CSV" button in the toolbar that triggers a native browser download via
   `window.location.href` assignment.
3. CSV columns are human-readable (no UIDs or foreign keys). Status uses the Django
   `get_FOO_display()` label, not the raw value.

---

## Success Metrics

- Clicking "Export CSV" with no filters downloads a file named `organizers.csv` containing
  every organizer in the DB.
- Clicking with `q=foo` and `status=confirmed` downloads only matching rows.
- CSV opens correctly in spreadsheet software (proper quoting, no broken encoding).
- No new Python packages in `requirements.txt`; no new npm packages.
- All 97 existing tests continue to pass after the change.

---

## Scope

**In scope:**
- New backend view + URL for organizer CSV export
- Export CSV button on the organizers list page
- Unit test for the new view (happy path + filtered path)

**Out of scope:**
- CSV export for other entity types (events, venues) — future work
- Server-side streaming / chunked response (row count is not expected to be millions)
- Authentication gate on the export endpoint (consistent with all other `/api/*` endpoints in this project — no auth bridge exists between Django and SvelteKit)
- Excel (`.xlsx`) format
- Date-stamped filenames

---

## Touchpoints

| File | Change |
|---|---|
| `apps/backend/events/views.py` | Add `api_organizers_export(request)` view function after `api_organizers` |
| `apps/backend/events/urls.py` | Add URL path for `/api/organizers/export/` — MUST be placed before the existing `/api/organizers/` catch-all |
| `apps/backend/events/tests.py` | Add test class `OrganizerExportTests` with 2 test methods |
| `apps/frontend/src/routes/organizers/+page.svelte` | Add `Download` import from lucide-svelte; add Export CSV button to toolbar |

---

## Public Contracts

**New endpoint:** `GET /api/organizers/export/`

| Param | Type | Behaviour |
|---|---|---|
| `q` | string (optional) | filter by name, city, or email (icontains, same logic as `api_organizers`) |
| `status` | string (optional) | filter by status value: `pending`, `confirmed`, `rejected` |

Response headers:
```
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="organizers.csv"
```

CSV column order (row 1 is header):
```
Name, Status, Email, Phone, Website, Address, City, Country,
Facebook, Instagram, Description, Source, Scraped At, Created At, Updated At
```

- `Status` uses Django's `get_status_display()` value: "Pending Review" / "Confirmed" / "Rejected"
- `Scraped At`, `Created At`, `Updated At`: ISO 8601 string if not null, else empty string
- All other fields: raw model value, empty string if blank

---

## Implementation Checklist

### Backend

1. **Open `apps/backend/events/views.py`.**
   After the closing `return JsonResponse(...)` of `api_organizers` (currently ends ~line 378),
   add a new function `api_organizers_export(request)`:
   - Import `csv` and `io` at the top of the file (check if already imported; add if not).
   - Import `HttpResponse` from `django.http` (check if already imported; add if not).
   - Build the same queryset as `api_organizers` (same `q` + `status` filter logic),
     but call `.order_by("name")` with **no** `Paginator` — fetch all rows.
   - Create a `HttpResponse` with `content_type="text/csv; charset=utf-8"`.
   - Set `response["Content-Disposition"] = 'attachment; filename="organizers.csv"'`.
   - Use `csv.writer(response)` to write directly to the response object (Django
     `HttpResponse` is file-like).
   - Write header row: `["Name", "Status", "Email", "Phone", "Website", "Address",
     "City", "Country", "Facebook", "Instagram", "Description", "Source",
     "Scraped At", "Created At", "Updated At"]`
   - For each organizer in the queryset, write one row using `o.get_status_display()`
     for the Status column. Format datetime fields with `.isoformat()` if not None,
     else empty string `""`.
   - Return `response`.

2. **Open `apps/backend/events/urls.py`.**
   Add the export URL path **immediately before** the existing `api/organizers/` path
   (line 24 currently). The new line:
   ```
   path("api/organizers/export/", views.api_organizers_export, name="api_organizers_export"),
   ```
   Placement is critical: Django matches paths top-to-bottom, and `api/organizers/`
   would swallow `api/organizers/export/` if listed first.

3. **Open `apps/backend/events/tests.py`.**
   Add class `OrganizerExportTests(TestCase)` with two test methods:
   - `test_export_all`: create 2 `Organizer` instances with different statuses, GET
     `/api/organizers/export/`, assert status 200, `Content-Type` contains `text/csv`,
     `Content-Disposition` contains `organizers.csv`, and both organizer names appear
     in the response content.
   - `test_export_filtered_by_status`: create 2 organizers (one `pending`, one
     `confirmed`), GET `/api/organizers/export/?status=confirmed`, assert only the
     confirmed organizer's name appears and the pending one does not.

### Frontend

4. **Open `apps/frontend/src/routes/organizers/+page.svelte`.**
   In the `<script>` block, add `Download` to the existing lucide-svelte import:
   ```ts
   import { Globe, Download } from 'lucide-svelte';
   ```

5. **In the same file, inside the toolbar `<div class="flex flex-wrap ...">` (the div
   that currently holds the status tabs and the search input), add the Export CSV button
   between the search input and the closing `</div>`.** The button must use
   `window.location.href` to trigger the download — no JS fetch, no CORS complexity.
   Construct the URL from the reactive `q` and `status` state variables. Only append
   params that are non-empty to keep the URL clean.

   The button should:
   - Be a `<button>` element (not an anchor) with `onclick` handler.
   - Label: "Export CSV" with `<Download size={16} />` icon to its left.
   - Style: match the existing page-control button pattern — `rounded-lg border
     border-border bg-surface px-3 py-2 text-sm font-medium text-muted
     transition-colors hover:text-text flex items-center gap-2`.
   - Build the export URL by starting with `/api/organizers/export/`, then appending
     `?q=<encodeURIComponent(q)>` if `q` is non-empty, and
     `&status=<encodeURIComponent(status)>` (or `?status=...` if `q` is empty) if
     `status` is non-empty.

---

## Blast Radius

- **Backend only (additive):** the new view and URL are purely additive. No existing view
  is modified. The URL ordering change in `urls.py` shifts the `api/organizers/` pattern
  one line down — this has no effect on any existing path resolution.
- **Frontend only (additive):** one new import and one new button element. No existing
  reactive state, API call, or table is modified.
- **Tests:** new test class only. Existing 97 tests are unaffected.
- **No migrations required** — no model changes.
- **No new dependencies** — `csv` and `io` are Python stdlib; `Download` is already in
  the installed lucide-svelte package.

---

## Failure Modes and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| URL order wrong — `/api/organizers/` matches before `/api/organizers/export/` | Medium (easy mistake) | Checklist step 2 explicitly says "immediately before"; test suite will catch a 404 |
| `csv` or `io` already imported differently | Low | Checklist step 1 says "check if already imported" before adding |
| Large dataset causes slow response | Low (admin tool, row count bounded) | Acceptable; streaming not required for this scope |
| `get_status_display()` returns unexpected string if status value is invalid | Very low | Only valid STATUS_CHOICES values are stored via model |
| Browser blocks non-user-gesture `window.location.href` | None — onclick IS a user gesture | N/A |
| Empty `q` or `status` appended as blank param | Low | Checklist step 5 says only append non-empty params |

---

## Verification Evidence

### Automated (run after implementation)

```bash
# From apps/backend/
python manage.py test events.tests.OrganizerExportTests --verbosity=2
# Must show 2 passed tests.

# Full suite must still be green
python manage.py test events --verbosity=1
# Must show 97 + 2 = 99 passed, 0 failures.
```

### Manual (in browser)

1. Start backend: `python manage.py runserver`
2. Start frontend: `pnpm dev` (from repo root)
3. Navigate to `http://localhost:5173/organizers/`
4. Click "Export CSV" with no filters — verify browser downloads `organizers.csv` and
   it opens in a spreadsheet with correct column headers and human-readable Status values.
5. Type a search term in the search box, click "Export CSV" — verify the downloaded CSV
   contains only matching rows.
6. Select a status tab (e.g., "Confirmed"), click "Export CSV" — verify only confirmed
   organizers appear.
7. Inspect the Status column in the CSV — values must be "Pending Review", "Confirmed",
   or "Rejected", not "pending", "confirmed", or "rejected".

---

## Acceptance Criteria

- [ ] `GET /api/organizers/export/` returns HTTP 200 with `Content-Type: text/csv`.
- [ ] `Content-Disposition` header is `attachment; filename="organizers.csv"`.
- [ ] CSV first row is the exact header: `Name,Status,Email,Phone,Website,Address,City,Country,Facebook,Instagram,Description,Source,Scraped At,Created At,Updated At`.
- [ ] Status column values are Django display labels, not raw choice keys.
- [ ] `?q=` and `?status=` params filter the export identically to the list API.
- [ ] Export returns ALL matching rows (no 50-row pagination cap).
- [ ] Clicking "Export CSV" button in the UI triggers a native browser file download.
- [ ] Filter state (`q`, `status`) is reflected in the export URL when the button is clicked.
- [ ] Button is visually consistent with the existing toolbar controls.
- [ ] `Download` icon appears to the left of the "Export CSV" label.
- [ ] 2 new tests pass (`test_export_all`, `test_export_filtered_by_status`).
- [ ] All 97 existing tests continue to pass (total: 99 green).
- [ ] No new entries in `requirements.txt` or `package.json`.
- [ ] No migrations generated or required.

---

## Dependencies and Sequencing

- Backend step (views.py) must be done before the URL step (urls.py) because `urls.py`
  references `views.api_organizers_export` — if the function doesn't exist yet, the
  Django URL resolver will fail on import.
- Frontend steps (4, 5) are independent of the backend steps and can be done in parallel,
  but the button will 404 in the browser until the backend is wired.
- Tests (step 3) can be written in any order relative to steps 1–2, but must pass before
  the plan is considered verified.

**Execution order:** Step 1 → Step 2 → Step 3 → Step 4 → Step 5 → Verification

---

## Resume and Execution Handoff

**Plan file:** `process/general-plans/active/csv-export-organizers_PLAN_18-06-26.md`

If EXECUTE is interrupted, resume by:
1. Checking which of the 5 checklist steps have been applied (read the four touchpoint
   files to determine current state).
2. Re-running the full test suite to confirm what is already working.
3. Continuing from the first uncompleted step.

EXECUTE must not deviate from the column list, URL pattern, or filter logic defined in
the Public Contracts section without returning to PLAN for approval.

---

*Plan complete — ready for EXECUTE mode.*
