"""Subprocess-based scraper runner.

``trigger_scraper_run`` is the public entrypoint: it guards against a duplicate
active run for the same key, creates a ``ScraperRun`` row, and spawns a *separate
OS process* (the ``run_scraper_job`` management command) that executes the scraper
and writes the result back to the row.

Why a subprocess instead of a thread: threads cannot be forcibly stopped from the
outside, so a thread-based run had no kill hook. A process can be killed — and by
launching it with ``start_new_session=True`` (POSIX ``setsid``), the child gets its
own process group. ``cancel_run`` then sends ``SIGTERM`` to that whole group via
``os.killpg``, which terminates the worker *and* any children it spawned (e.g.
Playwright's chromium). The ``ScraperRun`` DB row remains the only shared state
between the web process and the worker.

Cross-platform note: ``os.killpg`` / ``os.getpgid`` are POSIX-only. The dev/prod
environment is Linux, so no Windows support is required. ``start_new_session=True``
maps to ``CREATE_NEW_PROCESS_GROUP`` on Windows, but ``os.killpg`` does not exist
there — cancellation would need a different implementation on Windows.
"""
import os
import signal
import subprocess
import sys
import traceback  # noqa: F401  (kept for parity with worker error handling; safe import)

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import ScraperRun
from .notifications import notify_scraper_event
from .scrapers import SCRAPERS  # noqa: F401  (used by callers/tests via runner.SCRAPERS)

AVAILABLE_LOCATIONS = ["philippines", "singapore"]


def _map_result(result: dict) -> tuple[int, int, dict]:
    """Extract (created, updated, extra_counts) from a scraper run() result dict."""
    created = result.get("created", 0)
    updated = result.get("updated", 0)
    extra_counts = {
        k: v
        for k, v in result.items()
        if k not in ("source", "created", "updated")
    }
    return created, updated, extra_counts


def trigger_scraper_run(
    key: str,
    triggered_by=None,
    query_id: int | None = None,
    query_ids: list[int] | None = None,
    locations: list[str] | None = None,
):
    """Create a ScraperRun and spawn its worker subprocess.

    Returns ``(run, already_active)``. If a queued/running run already exists
    for ``key``, returns ``(None, True)`` and does not spawn anything — the
    caller maps this to HTTP 409.

    The worker runs as an independent process (``manage.py run_scraper_job``) in
    its own session/process group, so it can be killed wholesale by ``cancel_run``.

    ``query_id``: when set, the subprocess is given ``--query-id`` so only that
    single SearchQuery is processed. The ScraperRun key becomes
    ``"{key}:q:{query_id}"`` to allow concurrent single-query runs without
    conflicting with a full-source run or other single-query runs.

    ``query_ids``: when set (takes precedence over ``query_id``), the subprocess
    is given ``--query-ids`` so a targeted subset of SearchQuery rows is
    processed. The ScraperRun key stays plain ``key`` so this targeted-subset run
    occupies the scraper's main concurrency slot — it is a partial run of the full
    scraper, not an independent single-query run.
    """
    if query_ids is not None:
        run_key = key
    elif query_id:
        run_key = f"{key}:q:{query_id}"
    else:
        run_key = key

    active_exists = ScraperRun.objects.filter(
        scraper_key=run_key,
        status__in=[ScraperRun.Status.QUEUED, ScraperRun.Status.RUNNING],
    ).exists()
    if active_exists:
        return None, True

    try:
        run = ScraperRun.objects.create(scraper_key=run_key, triggered_by=triggered_by)
    except IntegrityError:
        # Two concurrent requests both passed the exists() check — the DB partial
        # unique constraint (unique_active_scraper_run) caught the duplicate.
        return None, True

    # BASE_DIR resolves to apps/backend/ (the dir containing manage.py).
    manage_py = settings.BASE_DIR / "manage.py"
    cmd = [sys.executable, str(manage_py), "run_scraper_job", "--run-id", str(run.id)]
    if query_ids is not None:
        cmd += ["--query-ids", ",".join(str(i) for i in query_ids)]
    elif query_id:
        cmd += ["--query-id", str(query_id)]
    if locations:
        cmd += ["--locations", ",".join(locations)]

    try:
        proc = subprocess.Popen(
            cmd,
            # POSIX setsid: give the child its own session + process group so the whole
            # tree (including Playwright's chromium) can be killed with os.killpg.
            start_new_session=True,
            cwd=str(settings.BASE_DIR),
        )
    except Exception:
        run.status = ScraperRun.Status.FAILED
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at", "updated_at"])
        notify_scraper_event("failed", scraper_key=key, run_id=run.id)
        raise

    # Store the pid synchronously so cancel_run has a target even for QUEUED runs.
    run.pid = proc.pid
    run.save(update_fields=["pid", "updated_at"])
    # Do NOT proc.wait() — the worker runs independently; the web process returns now.
    return run, False


def cancel_run(run_id: int):
    """Cancel an active scraper run by killing its process group.

    Returns ``(run, signal)`` where signal is one of:
      - ``"ok"``        — run was active and is now CANCELLED (or the worker beat us
                          to a terminal status, which we respect)
      - ``"not_found"`` — no run with that id (returns ``(None, "not_found")``)
      - ``"not_active"`` — run exists but is already terminal

    The SELECT FOR UPDATE + refresh_from_db dance guards the race where the worker
    writes SUCCESS/FAILED in the same instant we try to cancel.
    """
    with transaction.atomic():
        try:
            run = ScraperRun.objects.select_for_update().get(id=run_id)
        except ScraperRun.DoesNotExist:
            return None, "not_found"

        if not run.is_active:
            return run, "not_active"

        pid = run.pid
        if pid is not None:
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                # Subprocess already exited — nothing to kill.
                pass
            except PermissionError:
                # Shouldn't happen (same uid), but never crash the request.
                pass

        # Re-check inside the same transaction: the worker may have raced us to a
        # terminal state. If so, respect its outcome rather than overwriting it.
        run.refresh_from_db()
        if not run.is_active:
            return run, "ok"

        run.status = ScraperRun.Status.CANCELLED
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at", "updated_at"])
        return run, "ok"
