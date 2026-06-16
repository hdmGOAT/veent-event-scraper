# Venue Verification in Django Admin — PLAN

- **Created:** 2026-06-16
- **Status:** COMPLETED 2026-06-16 (implemented & verified — 14 tests pass)
- **Type:** SIMPLE
- **Owner:** vc-execute-agent
- **Scope:** `events` app — model field + migration + admin workflow

---

## 1. Goal

Let staff admins manually review venues and mark whether each is genuinely an
events venue. Reviewing happens **inside the existing Django admin** (which
already provides login). Each venue carries an approve/reject status, admins
work through a queue of pending venues, and access is limited to logged-in
`is_staff` users (Django's existing auth — no new auth system).

## 2. Decisions (confirmed with user)

| Question | Decision |
|---|---|
| Dashboard type | **Extend Django admin** — no separate custom UI |
| Verify flow | **Approve / Reject status** (pending → verified / rejected) + review queue |
| Auth scope | **Reuse Django auth** — any `is_staff` user; no new role/group |

## 3. Non-Goals

- No custom dashboard templates/views (Django admin only).
- No reviewer audit trail (who/when) — deliberately deferred; see Future Work.
- No auto-signals/heuristics to suggest a decision — deferred.
- No changes to scrapers, the public Web UI, or the Event model.

## 4. Design

### 4.1 Model change — `Venue.verification_status`

Add a `verification_status` CharField with `TextChoices` to `events/models.py`:

```python
class VerificationStatus(models.TextChoices):
    PENDING = "pending", "Pending review"
    VERIFIED = "verified", "Verified — events venue"
    REJECTED = "rejected", "Rejected — not an events venue"

verification_status = models.CharField(
    max_length=20,
    choices=VerificationStatus.choices,
    default=VerificationStatus.PENDING,
    db_index=True,
    help_text="Manual admin review state for whether this is a real events venue.",
)
```

- `default=PENDING` so every existing and newly scraped venue starts in the queue.
- `db_index=True` because the review queue filters on it constantly.
- Place the field near the other classification metadata in the model for readability.

**Migration:** `python manage.py makemigrations events` → produces
`0004_venue_verification_status.py`. Existing rows backfill to `pending` via the
default. No data migration needed.

### 4.2 Admin changes — `events/admin.py` `VenueAdmin`

1. **Show status in the list:** add `verification_status` to `list_display`.
2. **Filter / build the queue:** add `verification_status` to `list_filter`.
   (Clicking "Pending review" yields the review queue. Default queue link noted
   in §4.3.)
3. **Bulk review actions** — two admin actions so admins can approve/reject one
   or many selected venues from the changelist:

```python
@admin.action(description="Mark selected venues as VERIFIED (real events venue)")
def mark_verified(self, request, queryset):
    updated = queryset.update(verification_status=Venue.VerificationStatus.VERIFIED)
    self.message_user(request, f"{updated} venue(s) marked verified.")

@admin.action(description="Mark selected venues as REJECTED (not an events venue)")
def mark_rejected(self, request, queryset):
    updated = queryset.update(verification_status=Venue.VerificationStatus.REJECTED)
    self.message_user(request, f"{updated} venue(s) marked rejected.")

actions = ("mark_verified", "mark_rejected")
```

4. **Make the field editable on the detail page** — it's editable by default once
   added; ensure it is **not** in `readonly_fields`. Optionally add
   `list_editable = ("verification_status",)` so a reviewer can change status
   inline from the changelist without opening each venue (nice-to-have; include).

> `TextChoices` should be referenced as `Venue.VerificationStatus` — expose the
> inner class on the model (define it at module level or nested and aliased) so
> admin actions can reference it cleanly.

### 4.3 Review queue (no new code)

The "queue" is the admin changelist filtered to `verification_status=pending`.
- Reachable via the `list_filter` sidebar ("Pending review").
- Reviewer selects rows → runs **Mark verified** / **Mark rejected** action.
This satisfies the requirement with zero custom views.

### 4.4 Auth

No changes. Django admin already requires login and `is_staff`. Any existing
staff user can review. Confirmed acceptable.

## 5. Touchpoints (files changed)

| File | Change |
|---|---|
| `events/models.py` | Add `VerificationStatus` choices + `verification_status` field on `Venue` |
| `events/migrations/0004_*.py` | Auto-generated migration (makemigrations) |
| `events/admin.py` | `list_display`, `list_filter`, `list_editable`, two `@admin.action`s, `actions` |
| `events/tests.py` | Add tests (see §7) |

**Blast radius:** Low. Single app. Additive model field with a default — no
backfill risk, no impact on scrapers, Web UI, or Event model. The new field is
not referenced by `save_events`/upsert, so re-scrapes won't overwrite a
reviewer's decision (verify this in §7).

## 6. Implementation Steps

1. Add `VerificationStatus` + `verification_status` field to `Venue` in `events/models.py`.
2. `python manage.py makemigrations events` and review the generated migration.
3. Update `VenueAdmin` in `events/admin.py`: list_display, list_filter,
   list_editable, the two actions, and `actions` tuple.
4. `python manage.py migrate` against the dev DB.
5. Add tests (§7) and run them.
6. Manual smoke check in `/admin/` (§8).

## 7. Verification — Tests (`events/tests.py`)

The repo currently has **no test coverage**; add a small `TestCase`:

- `test_new_venue_defaults_to_pending` — a freshly created `Venue` has
  `verification_status == "pending"`.
- `test_mark_verified_action_updates_status` — invoke `mark_verified` with a
  queryset (or call `.update(...)`), assert status becomes `verified`.
- `test_rescrape_preserves_verification_status` — set a venue to `verified`, run
  the venue upsert path (`save_events`/`_upsert_venue` with the same
  `source`+`place_id`), assert `verification_status` is still `verified`.
  **This is the key regression guard** — confirms re-scraping does not reset
  reviewer decisions. If the upsert path *does* clobber it, surface that and add
  the field to the "do not overwrite on update" set.

Run: `python manage.py test events`

## 8. Manual Acceptance Check

1. `python manage.py runserver`, log into `/admin/` as a staff user.
2. Open Venues → confirm a "Verification status" column and a right-sidebar
   filter with Pending / Verified / Rejected.
3. Filter to **Pending review**, select venues, run **Mark verified** → rows move
   out of the pending filter; success message shows count.
4. Open a venue detail page → status is editable and saves.

## 9. Future Work (explicitly deferred)

- Reviewer audit trail: `verified_by` (FK to user) + `verified_at` timestamp.
- Auto-signals to assist decisions (has upcoming events, valid website, rating).
- A dedicated `reviewer` group/permission if review should be granted without
  full admin rights.
- Surface verification status in the public Web UI / filter out rejected venues.

## 10. Resume Handoff

- **Next action:** await user "ENTER EXECUTE MODE", then implement §6 in order.
- **Plan file:** `process/general-plans/active/venue-verification-admin_PLAN_16-06-26.md`
- **First edit:** `events/models.py` (add field) → makemigrations.
