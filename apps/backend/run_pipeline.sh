#!/usr/bin/env bash
# run_pipeline.sh — scrape → categorize → push
#
# Runs all three pipeline steps in sequence. Any step failure aborts the run
# and exits non-zero so cron/systemd can detect and alert on failures.
#
# Crontab (every 6 hours, adjust path to match server deployment):
#   0 */6 * * * /path/to/apps/backend/run_pipeline.sh
#
# Log rotation (delete logs older than 30 days):
#   0 1 * * * find /path/to/apps/backend/logs -name 'pipeline_*.log' -mtime +30 -delete
#
# Deployment checklist (run once before first cron fire):
#   1. Verify GROQ_API_KEY, GROQ_CATEGORIZE_MODEL are in .env
#   2. Run: python manage.py migrate   (applies migration 0027 for crm_pushed_at)
#   3. Run: python manage.py push_crm_leads --all --dry-run  (check push shape)
#   4. Run: python manage.py push_crm_leads --all            (one-time full backfill)
#   5. chmod +x apps/backend/run_pipeline.sh
#   6. Add crontab entry above with the correct absolute path

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/pipeline_$(date +%Y%m%d_%H%M%S).log"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== $(date -u '+%Y-%m-%dT%H:%M:%SZ') PIPELINE START ==="

cd "$SCRIPT_DIR"
source venv/bin/activate

echo "--- SCRAPE ---"
python manage.py scrape

echo "--- CATEGORIZE ---"
python manage.py categorize_events

echo "--- PUSH ---"
python manage.py push_crm_leads

echo "=== $(date -u '+%Y-%m-%dT%H:%M:%SZ') PIPELINE DONE ==="
