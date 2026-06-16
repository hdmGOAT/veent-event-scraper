# Venue Review UI (custom, outside Django admin) — PLAN

- **Created:** 2026-06-16
- **Status:** COMPLETED 2026-06-16 (implemented & verified — 21 tests pass)
- **Type:** COMPLEX (new views + URLs + templates + HTMX endpoint + auth + tests)
- **Owner:** vc-execute-agent
- **Depends on:** `venue-verification-admin_PLAN_16-06-26.md` (the `Venue.verification_status`
  field + `VerificationStatus` choices it added). That work is code-complete.
- **Surfaced skill:** `vc-frontend-design` / `vc-ui-ux-designer` for the build phase.

---

## 1. Goal

Replace the "ugly and hard to understand" Django admin as the venue-review surface with a
purpose-built, UX-friendly web UI. Staff log in (reusing Django auth) and move venues through
the review workflow with **one-click approve/reject** and **instant feedback (no full page
reload)**. The UI has three parts: a **dashboard** (status summary), a **review queue**
(filterable list), and a **venue detail** view (enough context to decide).

## 2. Decisions (confirmed with user)

| Question | Decision |
|---|---|
| Tech approach | **Django templates + HTMX** (server-rendered, instant inline status updates) |
| Scope | **Dashboard + review queue + venue detail** |
| Auth (carried over) | Reuse Django auth — `is_staff` required |

### 2.1 Styling decision (plan author's call — override if you disagree)

`templates/base.html` already defines a coherent dark design system via CSS variables
(`--bg`, `--card`, `--accent`, `.card`, `.pill`, etc.). The plan **reuses and extends that
design language** rather than introducing Tailwind — no build step, no new tooling, visually
consistent with the existing Events/Venues pages. HTMX is added via CDN `<script>`.
*If you'd prefer Tailwind (Play CDN), say so and I'll swap §4.4.*

## 3. Non-Goals

- No changes to the verification model/field (already exists) or to scrapers.
- No edit of venue data in this UI (status only). Full record editing stays in Django admin.
- No new auth system, registration, or password UI — Django's existing login only.
- No REST API / SPA. No audit trail (who/when) — deferred (see §10).
- Django admin is **kept** as-is (raw data management fallback).

## 4. Design

### 4.1 URLs — new `/review/` section (`events/urls.py`)

```python
# appended to events/urls.py (app_name = "events")
path("review/", views.review_dashboard, name="review_dashboard"),
path("review/venues/<slug:slug>/", views.review_venue_detail, name="review_venue_detail"),
path("review/venues/<slug:slug>/status/", views.review_set_status, name="review_set_status"),
```

- All three live under the existing `events` namespace → `events:review_dashboard`, etc.
- The status endpoint is **POST-only** and returns an HTML **partial**, not a redirect.

### 4.2 Views (`events/views.py`)

All three gated with `@staff_member_required` (from
`django.contrib.admin.views.decorators`) — redirects anonymous users to the admin login,
reusing existing auth with zero new code.

**`review_dashboard(request)`**
- Stats via a single aggregate:
  `Venue.objects.aggregate(total=Count("id"), pending=Count("id", filter=Q(verification_status="pending")), verified=..., rejected=...)`.
- Queue: `Venue.objects.annotate(event_count=Count("events"))`, filtered by
  `?status=` (default `pending`) and `?q=` (name/city icontains), ordered for review
  (e.g. `-event_count, name` so venues with events surface first). Reuse the existing
  `?q=` search idiom from `venue_list`.
- Renders `events/review/dashboard.html` with `stats`, `venues`, `status`, `q`,
  and the `VerificationStatus` choices for the filter tabs.

**`review_venue_detail(request, slug)`**
- `get_object_or_404(Venue, slug=slug)` + `venue.events.all()[:20]` for context.
- Renders `events/review/venue_detail.html` with venue, recent events, and the status control.

**`review_set_status(request, slug)`** — the HTMX action
- `require_POST`. Read `status` from `request.POST`; validate it is one of
  `Venue.VerificationStatus.values` → else `HttpResponseBadRequest`.
- `venue.verification_status = status; venue.save(update_fields=["verification_status", "updated_at"])`.
- Returns the rendered partial `events/review/_status_control.html` for that venue
  (HTMX swaps it in place). Because it's `update_fields`-scoped, it touches only the status —
  consistent with the re-scrape-safety guarantee from the prior feature.

### 4.3 Templates (`templates/events/review/`)

| Template | Role |
|---|---|
| `dashboard.html` | extends `base.html`; stat cards (pending/verified/rejected/total) + status filter tabs + search + queue of venue cards. Each card embeds `_status_control.html`. |
| `venue_detail.html` | extends `base.html`; venue context (website link, Google Maps link from `source_url`, rating, `primary_type_display`, amenities chips, recent events list) + a large `_status_control.html`. |
| `_status_control.html` | **partial** — current status badge + three buttons (Verify / Reject / Reset to pending). This is what the HTMX endpoint returns. Self-contained so it can swap itself via `hx-swap="outerHTML"`. |

**`_status_control.html` sketch:**
```html
<div class="status-control" id="status-{{ venue.pk }}">
  <span class="badge badge-{{ venue.verification_status }}">
    {{ venue.get_verification_status_display }}
  </span>
  {% for value, label in status_choices %}
    {% if value != venue.verification_status %}
      <button
        hx-post="{% url 'events:review_set_status' venue.slug %}"
        hx-vals='{"status": "{{ value }}"}'
        hx-target="#status-{{ venue.pk }}"
        hx-swap="outerHTML"
        class="btn btn-{{ value }}">{{ label }}</button>
    {% endif %}
  {% endfor %}
</div>
```
The view must pass `status_choices = Venue.VerificationStatus.choices` into the partial
context (both on first render and on the POST re-render).

### 4.4 HTMX + CSRF wiring (`templates/base.html`)

- Add HTMX via CDN in `{% block extra_head %}` or base head:
  `<script src="https://unpkg.com/htmx.org@2.0.3"></script>` (pin the version).
- CSRF: HTMX POSTs need the token. Add to `<body>`:
  `<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>` so every hx-post carries it.
  (Referencing `{{ csrf_token }}` also ensures the cookie/token is available.)
- Add new CSS tokens for status colors to the existing `<style>` block: green
  (verified), amber (pending), red (rejected) badges + button styles, reusing the
  existing `--card`/`--border` palette. Add a `.tabs`/`.stat-card` style consistent with
  the current `.pill`/`.card` look.

### 4.5 Navigation

Add a `Review` link to the header `<nav>` in `base.html` pointing to
`{% url 'events:review_dashboard' %}`, placed before the raw `/admin/` link, so the new UI
is the primary surface and admin is the fallback.

## 5. Touchpoints (files changed)

| File | Change |
|---|---|
| `events/urls.py` | 3 new routes |
| `events/views.py` | 3 new views (`review_dashboard`, `review_venue_detail`, `review_set_status`) + imports (`staff_member_required`, `require_POST`, `HttpResponseBadRequest`) |
| `templates/base.html` | HTMX script, `hx-headers` CSRF, status CSS tokens, `Review` nav link |
| `templates/events/review/dashboard.html` | new |
| `templates/events/review/venue_detail.html` | new |
| `templates/events/review/_status_control.html` | new partial |
| `events/tests.py` | new `ReviewUITests` (see §7) |

**Blast radius:** Medium-low. Additive — new URLs/views/templates; the only edit to existing
files is `base.html` (shared layout) and appending to `urls.py`/`views.py`. No model/migration
change. Reuses the existing `verification_status` field and design system.

## 6. Implementation Steps

1. Add the 3 views to `events/views.py` with `@staff_member_required`; `review_set_status`
   also `@require_POST`, validating `status` against `Venue.VerificationStatus.values`.
2. Wire the 3 routes in `events/urls.py`.
3. Update `base.html`: HTMX CDN script, `hx-headers` CSRF on `<body>`, status CSS tokens,
   `Review` nav link.
4. Create `templates/events/review/_status_control.html` (partial), then `dashboard.html`
   and `venue_detail.html` extending `base.html`.
5. Run tests (§7) and the manual smoke check (§8).

## 7. Verification — Tests (`events/tests.py` → `ReviewUITests`)

Use Django's test `Client` with a staff user (`User.objects.create_user(..., is_staff=True)`).

- `test_dashboard_requires_staff_login` — anonymous GET `/review/` redirects (302) to login;
  non-staff user also blocked.
- `test_dashboard_shows_status_counts` — create venues in each status; assert the aggregate
  counts render / are in context.
- `test_queue_filters_by_status` — `?status=pending` lists only pending venues.
- `test_set_status_updates_and_returns_partial` — POST `status=verified` to the status URL
  as staff; assert DB row updated to `verified` and response contains the status badge
  partial (HTTP 200, not a redirect).
- `test_set_status_rejects_invalid_value` — POST `status=bogus` → 400, DB unchanged.
- `test_set_status_requires_post` — GET the status URL → 405.
- `test_set_status_requires_staff` — anonymous POST → redirect/403, DB unchanged.

Run: `./venv/bin/python manage.py test events`

## 8. Manual Acceptance Check

1. `./venv/bin/python manage.py runserver`; visit `/review/` while logged out → bounced to login.
2. Log in as staff → dashboard shows pending/verified/rejected/total cards + a pending queue.
3. Click **Verify** on a card → badge flips to green **in place, no page reload**; the count
   cards reflect the change on next load; the venue leaves the pending filter.
4. Open a venue detail → see website/map/rating/amenities/recent events + large status buttons;
   change status there too.
5. Confirm the `Review` link appears in the top nav and `/admin/` still works as fallback.

## 9. Risks / Watch-outs

- **CSRF with HTMX:** if POSTs 403, the `hx-headers` X-CSRFToken on `<body>` is missing or the
  token isn't rendered — verify in step 3.
- **HTMX availability offline:** CDN dependency. Acceptable for an internal admin tool; if
  offline use is needed later, vendor `htmx.min.js` into static files.
- **Status enum drift:** validate POST against `VerificationStatus.values` so a bad/old value
  can't be written.
- **Pagination:** queue is unpaginated initially. If venue volume is large, add Django
  `Paginator` (note, not blocking for first ship).

## 10. Future Work (deferred)

- Audit trail (`verified_by` / `verified_at`) surfaced in the detail view.
- Bulk approve/reject in the queue (HTMX multi-select).
- Pagination + sort controls on the queue.
- Auto-signals (has upcoming events, valid website, rating) shown as decision hints.
- Optional: retire the admin verification action once this UI is trusted.

## 11. Resume Handoff

- **Next action:** await user "ENTER EXECUTE MODE", then implement §6 in order.
- **Plan file:** `process/general-plans/active/venue-review-ui_PLAN_16-06-26.md`
- **First edit:** `events/views.py` (add the 3 staff-gated views).
- **Depends on:** `verification_status` field (already implemented).
