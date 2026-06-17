# Public Organizers Page

Date: 17-06-26
Complexity: Simple
Status: ⏳ PLANNED

## Overview

Add a public, read-only **list + detail** view for the existing `Organizer` model,
mirroring the existing `venue_list` / `venue_detail` pattern (server-rendered Django
templates, no auth, no JS framework). This is NOT the staff `/review/` UI — it is a
public-facing directory of event organizers for site visitors. Only `confirmed`
organizers are publicly visible; `pending` and `rejected` organizers stay hidden from
the public surface and continue to be managed exclusively via Django admin /
the existing internal review workflows.

## Quick Links

- [Goals and Success Metrics](#goals-and-success-metrics)
- [Phase Completion Rules](#phase-completion-rules)
- [Execution Brief](#execution-brief)
- [Scope](#scope)
- [Key Decisions Locked In](#key-decisions-locked-in)
- [Functional Requirements](#functional-requirements)
- [Acceptance Criteria](#acceptance-criteria)
- [Implementation Checklist](#implementation-checklist)
- [Risks and Mitigations](#risks-and-mitigations)
- [Integration Notes](#integration-notes)
- [Touchpoints](#touchpoints)
- [Public Contracts](#public-contracts)
- [Blast Radius](#blast-radius)
- [Verification Evidence](#verification-evidence)
- [Resume and Execution Handoff](#resume-and-execution-handoff)
- [Cursor + RIPER-5 Guidance](#cursor--riper-5-guidance)

---

## Goals and Success Metrics

- A visitor can browse a list of confirmed organizers at `/organizers/` and search by
  name/city.
- A visitor can view a single organizer's detail page at `/organizers/<slug>/` showing
  contact info (website, email, phone, social links, address) and a best-effort list of
  events attributed to that organizer's name.
- `pending` and `rejected` organizers are not reachable through the public list or detail
  URL (404 on direct slug access) — only the internal admin/review surfaces can see them.
- Existing staff review workflows, admin, and scraper persistence are untouched.
- Full test suite (`./venv/bin/python manage.py test events`) stays green, with new tests
  added for the new views.

## Phase Completion Rules

A phase is NOT complete until:

1. **Integration Test** - Works with other system pieces (URLs resolve, templates render
   inside `base.html`, nav link works)
2. **Manual Test** - A developer can load `/organizers/` and `/organizers/<slug>/` in a
   browser/dev server and see correct data
3. **Data Verification** - Confirm via Django shell or test assertions that only
   `confirmed` organizers appear in the public queryset
4. **Error Handling** - Non-existent or non-confirmed slugs return 404, not a 500 or a
   silent leak of hidden data
5. **User Confirmation** - User (or test suite, standing in for manual confirmation in this
   simple non-interactive feature) confirms list/detail/search/visibility all behave as
   specified

Status meanings:
- ⏳ PLANNED - Not started
- 🔨 CODE DONE - Written but not E2E tested
- 🧪 TESTING - Currently being tested
- ✅ VERIFIED - Tested AND confirmed working
- 🚧 BLOCKED - Has issues

After this single-phase plan, document:
- [ ] What was tested manually (dev server walkthrough of both URLs + search)
- [ ] Data verified in DB (test assertions covering visibility filter)
- [ ] Errors encountered and fixed (if any)
- [ ] User confirmation received

---

## Execution Brief

This is a single logical phase (SIMPLE plan, one session). Breaking it into three
sub-stages for traceability:

### Stage A — Model + queryset decision
**What happens:** Add `Organizer.get_absolute_url()`. Confirm the public visibility filter
(`status=confirmed`) is the only gate applied anywhere in the new views.
**Test:** `./venv/bin/python manage.py shell -c "from events.models import Organizer; o = Organizer.objects.create(name='Test Org', slug='test-org', status='confirmed'); print(o.get_absolute_url())"` prints `/organizers/test-org/`.
**Verify:** Manual shell check above; no migration needed (method, not a field).
**Done when:** `get_absolute_url` exists and resolves to the new `organizer_detail` URL name.

### Stage B — Views + URLs
**What happens:** Add `organizer_list` and `organizer_detail` view functions to
`events/views.py`, each filtering to `status=Organizer.STATUS_CONFIRMED`. Wire two new
`path()` entries into `events/urls.py` under the `events` namespace.
**Test:** `./venv/bin/python manage.py runserver` then visit `/organizers/` and
`/organizers/<slug>/` for a manually created confirmed organizer; visit a pending
organizer's slug directly and confirm 404.
**Verify:** `reverse("events:organizer_list")` and `reverse("events:organizer_detail", args=[slug])` resolve without error in a shell/test.
**Done when:** Both views render 200 for confirmed organizers and 404 for
pending/rejected/non-existent slugs.

### Stage C — Templates + nav + tests
**What happens:** Create `templates/events/organizer_list.html` and
`organizer_detail.html` following the existing dark CSS-variable design system (mirror
`venue_list.html` / `venue_detail.html` markup conventions: `.card`, `.grid`, `.search`,
`.meta`, `.muted`, `.pill`, `.empty`). Add an "Organizers" link to `templates/base.html`
nav. Add tests to `events/tests.py` covering list rendering, search, detail rendering,
visibility filtering, and 404s.
**Test:** `./venv/bin/python manage.py test events` — all tests pass, including new ones.
**Verify:** Read test output; confirm new `OrganizerPublicViewTests`-style test class
results show as `OK`.
**Done when:** Full suite green, nav link visible on every page, organizer cards display
contact info, detail page shows "Events by this organizer" section (possibly empty).

**Expected Outcome:**
- `/organizers/` lists confirmed organizers with name/city/website search.
- `/organizers/<slug>/` shows one confirmed organizer's contact details and any events
  whose free-text `organizer` field case-insensitively matches the organizer's `name`.
- Pending/rejected organizers are invisible on both the public list and via direct slug
  access (404).
- Nav bar includes an "Organizers" link alongside Events/Venues.
- All existing and new automated tests pass.

---

## Scope

**In scope:**
- `events/models.py`: add `Organizer.get_absolute_url()`.
- `events/views.py`: add `organizer_list(request)` and `organizer_detail(request, slug)`.
- `events/urls.py`: add `organizers/` and `organizers/<slug:slug>/` URL patterns.
- `templates/events/organizer_list.html` (new).
- `templates/events/organizer_detail.html` (new).
- `templates/base.html`: add nav link to organizer list.
- `events/tests.py`: new `TestCase` class(es) covering the above.

**Out of scope:**
- Any change to the staff `/review/` UI, `OrganizerAdmin`, or scraper persistence
  (`save_organizers`).
- Adding a real FK between `Event` and `Organizer` (the free-text match is a known,
  explicitly accepted limitation — see Key Decisions below).
- Pagination (current `venue_list`/`event_list` don't paginate either; consistent to skip
  for now — note as Future Work, not a blocker).
- Any new auth, permission, or HTMX behavior (read-only public pages, full reload search
  forms, exactly like the venue/event list pattern).
- New migrations (no schema fields are being added — `get_absolute_url` is a Python method
  only).

---

## Key Decisions Locked In

1. **Public visibility filter — only `status=confirmed` organizers are public.**
   Rationale: `pending` means "not yet reviewed," and `rejected` means "determined not
   legitimate/relevant." Showing either to the public risks displaying unvetted or
   explicitly-rejected entities (e.g. wrong contact info, spam, or organizers an admin
   has actively disqualified). `confirmed` is the only status that represents admin
   sign-off. This mirrors how `Venue.verification_status` gates the `/review/` UI's
   intent, applied here directly to public visibility instead. Both `organizer_list` and
   `organizer_detail` apply `Organizer.objects.filter(status=Organizer.STATUS_CONFIRMED)`
   as the base queryset — `get_object_or_404` against that filtered queryset means a
   pending/rejected slug 404s exactly like a nonexistent one (no leakage of existence).

2. **Linking events to organizers — free-text case-insensitive name match, no FK.**
   `Event.organizer` is a plain `CharField`, not a FK to `Organizer` (confirmed in
   `events/models.py`). Adding a real FK is a bigger migration-and-backfill project (event
   data currently has manually-entered organizer strings from multiple scrapers, with no
   guaranteed 1:1 name match) and is explicitly out of scope here. The detail view instead
   does a best-effort match: `Event.objects.filter(organizer__iexact=organizer.name)`,
   ordered the same as `event_list` (`starts_at`, `name`). This is a known limitation:
   organizers whose name in `Organizer.name` doesn't exactly match the string stored on
   `Event.organizer` (typos, abbreviations, "Inc." suffixes, etc.) will show zero events
   even if events conceptually belong to them. Document this inline as a code comment and
   in Future Work below. Template renders an empty-state message when no matches are
   found (consistent with `venue_detail.html`'s "No events recorded for this venue yet.").

3. **`get_absolute_url`** — add to `Organizer` model (currently missing — verified absent
   in `events/models.py` read above) pointing at `reverse("events:organizer_detail",
   args=[self.slug])`, matching the `Venue`/`Event` pattern exactly.

4. **Search** — `?q=` query param, case-insensitive `icontains` across `name` and `city`
   only (mirrors `venue_list`'s `Q(name__icontains=query) | Q(city__icontains=query)`).
   No category/status filter control on the public page (status is fixed to confirmed,
   not user-selectable).

5. **Nav link** — add `<a href="{% url 'events:organizer_list' %}">Organizers</a>` to
   `templates/base.html`, positioned between "Venues" and "Review" (public-facing links
   grouped together, internal "Review"/"Admin" links last — matches existing visual
   grouping intent).

---

## Functional Requirements

- `GET /organizers/` returns 200, renders `organizer_list.html`, lists only `confirmed`
  organizers ordered by name (model `Meta.ordering` already is `["name"]`).
- `GET /organizers/?q=<term>` filters the above list by case-insensitive substring match
  on `name` or `city`.
- `GET /organizers/<slug>/` returns 200 for a confirmed organizer's slug, renders
  `organizer_detail.html` with full contact info and a list of matching events.
- `GET /organizers/<slug>/` returns 404 for a slug belonging to a pending or rejected
  organizer, or a slug that does not exist at all.
- List and detail templates display: name, status is NOT shown publicly (status is an
  internal workflow field; showing "confirmed" everywhere is just noise — omit it from
  the public template entirely), website, email, phone, address/city/country, Facebook
  and Instagram links (when present), description (detail page only).
- Empty-state message shown when no organizers match a search, and when an organizer has
  no description / no matched events.
- Nav bar on every page includes a working "Organizers" link.

## Acceptance Criteria

- [ ] `Organizer.get_absolute_url()` exists and returns `/organizers/<slug>/`.
- [ ] `events:organizer_list` and `events:organizer_detail` URL names resolve.
- [ ] `/organizers/` returns 200 and only includes organizers with `status="confirmed"`.
- [ ] `/organizers/?q=...` filters by name/city, case-insensitive.
- [ ] `/organizers/<slug>/` for a confirmed organizer returns 200 and shows contact
      fields + matched events (or an empty-state message).
- [ ] `/organizers/<pending-slug>/` and `/organizers/<rejected-slug>/` return 404.
- [ ] `/organizers/<nonexistent-slug>/` returns 404 (same response shape as the above —
      no distinguishable behavior that would leak existence of hidden organizers).
- [ ] Nav link "Organizers" appears on every page rendered via `base.html`.
- [ ] No changes to `OrganizerAdmin`, `/review/` views, or `save_organizers`.
- [ ] `./venv/bin/python manage.py test events` passes in full, including new tests.
- [ ] No new Django migration is generated (`python manage.py makemigrations --check`
      should show no changes, since only a method was added).

---

## Implementation Checklist

1. **Code:** In `events/models.py`, add `get_absolute_url(self)` to the `Organizer` class
   (after `__str__`), returning `reverse("events:organizer_detail", args=[self.slug])`.
   **Test:** none yet (covered by Stage C tests); confirm no migration needed by running
   `./venv/bin/python manage.py makemigrations --check --dry-run` (expect "No changes
   detected").

2. **Code:** In `events/views.py`, import `Organizer` alongside `Event, Venue` in the
   existing `from .models import Event, Venue` line (becomes
   `from .models import Event, Organizer, Venue`).
   **Test:** none (import-only); will be exercised by Step 3.

3. **Code:** In `events/views.py`, add `organizer_list(request)`:
   - `query = request.GET.get("q", "").strip()`
   - `organizers = Organizer.objects.filter(status=Organizer.STATUS_CONFIRMED)`
   - if `query`: filter with `Q(name__icontains=query) | Q(city__icontains=query)`
   - render `events/organizer_list.html` with `{"organizers": organizers, "query": query}`
   **Test:** covered in Step 8 (`test_organizer_list_shows_only_confirmed`,
   `test_organizer_list_search_filters_by_name_and_city`).

4. **Code:** In `events/views.py`, add `organizer_detail(request, slug)`:
   - `organizer = get_object_or_404(Organizer.objects.filter(status=Organizer.STATUS_CONFIRMED), slug=slug)`
   - `events = Event.objects.filter(organizer__iexact=organizer.name).select_related("venue")`
     ordered by `starts_at, name` (inherits model default ordering — no explicit
     `.order_by()` needed unless test reveals otherwise)
   - render `events/organizer_detail.html` with `{"organizer": organizer, "events": events}`
   - inline comment explaining the free-text match limitation (per Key Decision 2)
   **Test:** covered in Step 8 (`test_organizer_detail_shows_matched_events`,
   `test_organizer_detail_404_for_pending_and_rejected_and_missing`).

5. **Code:** In `events/urls.py`, add two `path()` entries in the public section (before
   the "Staff-only venue review UI" comment block):
   ```
   path("organizers/", views.organizer_list, name="organizer_list"),
   path("organizers/<slug:slug>/", views.organizer_detail, name="organizer_detail"),
   ```
   **Test:** covered by Step 8's `reverse()` usage inside test cases (implicit
   verification — if the URL name is wrong, tests fail immediately with `NoReverseMatch`).

6. **Code:** Create `templates/events/organizer_list.html` extending `base.html`,
   following `templates/events/venue_list.html`'s structure (title block, search form
   posting `?q=` via GET to `events:organizer_list`, `.grid`/`.card` layout, `.empty`
   fallback message). Each card shows: name (linked via `get_absolute_url`), city/country
   (if present), website link (if present), email/phone (if present, as plain text — not
   itself security-sensitive, already public admin-confirmed contact info). No status pill
   (status is an internal field, not shown publicly per Key Decision above).
   **Test:** covered in Step 8 (response content assertions, e.g.
   `assertContains(resp, organizer.name)`).

7. **Code:** Create `templates/events/organizer_detail.html` extending `base.html`,
   following `templates/events/venue_detail.html`'s structure: back-link to
   `events:organizer_list`, `<h1>{{ organizer.name }}</h1>`, contact `.meta` block
   (website/email/phone/address/city/country/facebook_url/instagram_url, each
   conditionally rendered), `description` paragraph (if present, using the existing
   `.about` class for visual consistency with venue detail), then an "Events" `<h2>` +
   `.grid` of event cards (mirroring `venue_detail.html`'s event-card markup exactly,
   including the `.empty` fallback "No events recorded for this organizer yet." when the
   `events` queryset is empty).
   **Test:** covered in Step 8.

8. **Code + Test:** In `events/tests.py`, add a new `TestCase` class
   `OrganizerPublicViewTests` with the following test methods (place after the existing
   `ReviewUITests` class, no changes to existing classes):
   - `test_organizer_list_shows_only_confirmed` — create one confirmed, one pending, one
     rejected organizer; assert only the confirmed one's name appears in
     `resp.context["organizers"]` and in `resp.content`.
   - `test_organizer_list_search_filters_by_name_and_city` — create two confirmed
     organizers with distinct names/cities; assert `?q=<term>` returns only the matching
     one.
   - `test_organizer_detail_returns_200_for_confirmed` — create a confirmed organizer;
     `GET` its `get_absolute_url()`; assert 200 and contact fields appear in content.
   - `test_organizer_detail_shows_matched_events` — create a confirmed organizer named
     "Race Co", create an `Event` with `organizer="Race Co"` (and one with
     `organizer="Other Co"` as a negative control); assert only the matching event's name
     appears in `resp.context["events"]` / content.
   - `test_organizer_detail_404_for_pending_rejected_and_missing` — create a pending
     organizer and a rejected organizer; assert `GET` on each of their detail URLs returns
     404; assert `GET /organizers/does-not-exist/` also returns 404.
   - `test_organizer_get_absolute_url` — unit-test the model method directly:
     `Organizer(slug="acme").get_absolute_url() == "/organizers/acme/"`.
   **Run command:** `./venv/bin/python manage.py test events`
   **Pass criteria:** all tests pass, including all pre-existing tests (no regressions).

9. **Code:** In `templates/base.html`, add the nav link
   `<a href="{% url 'events:organizer_list' %}">Organizers</a>` immediately after the
   existing `<a href="{% url 'events:venue_list' %}">Venues</a>` line and before the
   `Review` link.
   **Test:** covered implicitly — any existing test that does `assertContains` on nav
   content would catch a broken `{% url %}` tag via a `NoReverseMatch` 500. Explicitly
   verify by loading any existing page test (e.g. run the full suite in Step 8) and
   confirming no new failures appear on previously-passing view tests (`event_list`,
   `venue_list`, etc., if such tests exist — confirm via `grep -n "def test_" events/tests.py` during EXECUTE).

10. **Verify (manual):** Run `./venv/bin/python manage.py runserver`, visit
    `http://127.0.0.1:8000/organizers/` and a confirmed organizer's detail page in a
    browser. Confirm nav link works from any page. Confirm `?q=` search behaves as
    expected with at least one real or manually-created confirmed organizer in the dev DB.

11. **Verify (automated):** Run `./venv/bin/python manage.py test events` — full suite
    green. Run `./venv/bin/python manage.py makemigrations --check --dry-run` — confirm
    "No changes detected" (the `get_absolute_url` method change must not trigger a
    migration; if it does, something else changed unexpectedly — investigate before
    proceeding).

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Free-text `organizer__iexact` match misses real events for an organizer (typos/variants in scraped data) | Documented as an explicit, accepted limitation (Key Decision 2). Detail page shows an honest empty-state rather than silently failing. Revisit with a real FK migration as Future Work if this becomes a product priority. |
| Public page accidentally leaks pending/rejected organizer existence (e.g. distinguishable 404 vs no-such-slug) | Both cases resolve through the same `get_object_or_404` against the `status=confirmed`-filtered queryset, producing an identical generic 404 — no separate code path exists that could leak state. |
| Nav link added to `base.html` breaks an existing test asserting exact nav HTML | Search `events/tests.py` for any exact-match assertions on nav markup before editing (`grep -n "Venues\|nav" events/tests.py`); none found in the version read during planning, but EXECUTE must re-check current file state before editing. |
| New view introduces an N+1 query risk for events-by-organizer | `select_related("venue")` is applied on the `Event` queryset in `organizer_detail`, matching the existing `event_list`/`venue_detail` pattern. |
| Status field accidentally shown publicly during template authoring (copy-paste from `OrganizerAdmin` fields) | Explicit instruction in Step 6/7 to omit status from both templates; reviewed at EXECUTE time. |

## Integration Notes

- **Dependencies:** None beyond existing Django/app code — no new packages, no new
  settings, no new migrations.
- **Environment:** No env var changes.
- **Data model touches:** One new Python method (`Organizer.get_absolute_url`) — zero
  schema/migration impact. Confirmed via `makemigrations --check --dry-run` in Step 11.
- **Existing systems untouched:** `OrganizerAdmin` (`events/admin.py`), the `/review/`
  staff UI (`review_dashboard`, `review_venue_detail`, `review_set_status` — all
  Venue-only, unaffected regardless), and `save_organizers` (`events/scrapers/base.py`)
  are not modified by this plan.

---

## Touchpoints

| File | Change |
|---|---|
| `events/models.py` | Add `Organizer.get_absolute_url()` method (no field/migration change) |
| `events/views.py` | Add `organizer_list`, `organizer_detail` functions; update `Organizer` import |
| `events/urls.py` | Add `organizers/` and `organizers/<slug:slug>/` paths under `events` namespace |
| `templates/events/organizer_list.html` | New file |
| `templates/events/organizer_detail.html` | New file |
| `templates/base.html` | Add one nav `<a>` link |
| `events/tests.py` | Add `OrganizerPublicViewTests` class (new tests only, no edits to existing classes) |

No changes to: `events/admin.py`, `events/scrapers/*`, `events/management/commands/scrape.py`, `config/*`, any migration file.

## Public Contracts

- **New URL names** (in `events` namespace): `events:organizer_list` → `/organizers/`,
  `events:organizer_detail` → `/organizers/<slug>/`. These are additive; no existing URL
  name changes.
- **New template contract:** `organizer_list.html` expects context `{organizers, query}`;
  `organizer_detail.html` expects context `{organizer, events}`. Both are new contracts,
  not modifications of existing ones.
- **`Organizer.get_absolute_url()`** is a new public method on the model — additive, safe
  for any future code (e.g. admin "view on site" links) to rely on.
- **No changes** to any existing URL name, view signature, template contract, admin
  contract, or scraper persistence function signature (`save_organizers`,
  `save_events`).

## Blast Radius

- **Files touched:** 6 (2 new templates, 4 edited files: models, views, urls, base
  template) plus 1 test file addition — 7 total.
- **Runtime surfaces affected:** public web UI only (new routes). Django admin, the
  `/review/` staff UI, and all scrapers are unaffected — no shared code paths beyond the
  `Organizer` model itself (read-only access from the new views).
- **Database:** zero schema change. Read-only queries added; no writes introduced by this
  feature.
- **Backwards compatibility:** fully additive. No existing URL, view, template, or admin
  behavior changes. Safe to ship without a migration or deployment coordination beyond a
  normal code deploy.
- **Failure mode if something goes wrong:** worst case is a 500 on the two new routes
  (e.g. template syntax error) — does not affect any other page, since `base.html`'s nav
  link change is the only shared-file edit, and it is additive (one new `<a>` tag).

## Verification Evidence

Required before declaring this plan done:

1. **Automated:** `./venv/bin/python manage.py test events` output showing all tests pass
   (including the 6 new `OrganizerPublicViewTests` methods and zero regressions in the
   pre-existing 21+ tests).
2. **Migration safety:** `./venv/bin/python manage.py makemigrations --check --dry-run`
   output showing "No changes detected in app 'events'".
3. **Manual smoke test:** dev server screenshot or terminal confirmation of `/organizers/`
   and one `/organizers/<slug>/` page rendering correctly, plus one 404 confirmation for a
   pending/rejected slug (e.g. via `curl -I` or browser).
4. **Visibility check:** at minimum, the automated test
   `test_organizer_list_shows_only_confirmed` and
   `test_organizer_detail_404_for_pending_rejected_and_missing` must pass — these are the
   two tests that directly prove the core visibility decision (Key Decision 1) is
   correctly implemented.

## Resume and Execution Handoff

If EXECUTE is resumed in a new session after compaction or interruption, read in this
order:
1. This plan file in full (`process/general-plans/active/2026-06-17-organizers-page-PLAN.md`).
2. `events/models.py` — confirm current state of `Organizer` class (verify
   `get_absolute_url` not already added by a partial prior run).
3. `events/views.py` — confirm whether `organizer_list`/`organizer_detail` already exist
   (idempotency check before re-adding).
4. `events/urls.py` — confirm whether the two new `path()` entries already exist.
5. `events/tests.py` — check for an existing `OrganizerPublicViewTests` class to avoid
   duplicate test names.
6. Re-run `./venv/bin/python manage.py test events` first, before making any further
   edits, to establish the current actual state versus this plan's assumptions.

No partial migration state to worry about — this plan generates no migrations. Resuming
mid-plan is safe as long as Implementation Checklist steps are treated as idempotent
(check file state before re-adding code).

---

## Cursor + RIPER-5 Guidance

- **Cursor Plan mode:** Import the "Implementation Checklist" (11 steps) directly. After
  Step 11, update the status strip at the top of this file to ✅ VERIFIED.
- **RIPER-5 mode:**
  - RESEARCH/INNOVATE: already completed (see Key Decisions Locked In above — read
    against actual `events/models.py`, `events/views.py`, `events/urls.py`,
    `events/admin.py`, `templates/events/venue_*.html`, `templates/base.html`,
    `events/tests.py`).
  - PLAN: this file. Awaiting user approval.
  - EXECUTE: implement Steps 1–11 exactly as specified; do not deviate from the visibility
    filter (Key Decision 1) or the free-text match approach (Key Decision 2) without
    pausing and updating this plan first.
  - After EXECUTE: run the full Verification Evidence checklist before reporting done.
  - If scope changes mid-run (e.g. user wants pagination or a real Event–Organizer FK):
    pause, treat as a Change Management event, update this plan file, then continue.

---

## Future Work (explicitly out of scope now)

- Real FK between `Event` and `Organizer` (would require data migration/backfill of
  existing free-text `organizer` values — a separate, larger plan).
- Pagination for `/organizers/` if the organizer count grows large.
- Organizer logo/avatar image field.
- Public-facing "verified organizer" badge (currently no such concept distinct from
  `status=confirmed`, which is intentionally not shown — could be a future UX decision).
