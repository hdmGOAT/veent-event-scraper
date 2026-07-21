#!/usr/bin/env bash
# Sync all GitHub Actions secrets for veent-event-scraper.
# Run from the repo root — safe to re-run (overwrites existing secrets).
#
# Usage: ./sync-secrets.sh [repo]
# Example: ./sync-secrets.sh hdmGOAT/veent-event-scraper
#
# Flags:
#   --cookies-only   Only re-sync cookie files (useful when cookies expire)
#   --infra-only     Only set infra + app secrets (skip cookies)

set -euo pipefail

REPO="${1:-hdmGOAT/veent-event-scraper}"
MODE="all"
[[ "${*}" == *"--cookies-only"* ]] && MODE="cookies"
[[ "${*}" == *"--infra-only"* ]] && MODE="infra"

FB_COOKIES="apps/backend/www.facebook.com_cookies.txt"
IG_COOKIES="apps/backend/www.instagram.com_cookies.txt"

LOG_FILE="sync-secrets-$(date +%Y%m%d-%H%M%S).log"
ERRORS=0

log() {
  local level="$1"; shift
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*"
  echo "$msg"
  echo "$msg" >> "$LOG_FILE"
}

info()    { log "INFO " "$@"; }
success() { log "OK   " "$@"; }
warn()    { log "WARN " "$@"; }
error()   { log "ERROR" "$@" >&2; (( ERRORS++ )) || true; }

set_secret() {
  local name="$1"
  local value="$2"
  if printf '%s' "$value" | gh secret set "$name" --repo "$REPO" 2>> "$LOG_FILE"; then
    success "$name set"
  else
    error "$name FAILED"
  fi
}

prompt_secret() {
  local name="$1"
  local description="$2"
  echo ""
  info "$name — $description"
  printf '  Value: '
  local value
  read -rs value
  echo ""
  if printf '%s' "$value" | gh secret set "$name" --repo "$REPO" 2>> "$LOG_FILE"; then
    success "$name set"
  else
    error "$name FAILED"
  fi
}

# ── Cookies (file-based) ──────────────────────────────────────────────────────
sync_cookies() {
  info "Syncing cookie files..."

  if [ ! -f "$FB_COOKIES" ]; then
    error "$FB_COOKIES not found — skipping FB_COOKIES_B64"
  else
    if base64 -w 0 "$FB_COOKIES" | gh secret set FB_COOKIES_B64 --repo "$REPO" 2>> "$LOG_FILE"; then
      success "FB_COOKIES_B64 set ($(wc -c < "$FB_COOKIES") bytes)"
    else
      error "FB_COOKIES_B64 FAILED"
    fi
  fi

  if [ ! -f "$IG_COOKIES" ]; then
    error "$IG_COOKIES not found — skipping IG_COOKIES_B64"
  else
    if base64 -w 0 "$IG_COOKIES" | gh secret set IG_COOKIES_B64 --repo "$REPO" 2>> "$LOG_FILE"; then
      success "IG_COOKIES_B64 set ($(wc -c < "$IG_COOKIES") bytes)"
    else
      error "IG_COOKIES_B64 FAILED"
    fi
  fi
}

# ── Known defaults (non-sensitive) ───────────────────────────────────────────
sync_defaults() {
  info "Setting known defaults..."
  set_secret SSH_USER               "root"
  set_secret DEBUG                  "false"
  set_secret ENVIRONMENT            "production"
  set_secret GROQ_MODEL             "llama-3.3-70b-versatile"
  set_secret GROQ_CATEGORIZE_MODEL  "llama-3.1-8b-instant"
  set_secret POSTGRES_DB            "veent"
}

# ── Interactive secrets (sensitive) ──────────────────────────────────────────
sync_interactive() {
  info "Prompting for sensitive secrets (input is hidden)..."
  prompt_secret SSH_HOST          "VM IP address"
  prompt_secret SSH_PRIVATE_KEY   "contents of ~/.ssh/id_ed25519"
  prompt_secret DOMAIN            "public domain (e.g. scraper.veent.io)"
  prompt_secret SECRET_KEY        "Django secret key (python -c \"import secrets; print(secrets.token_urlsafe(50))\")"
  prompt_secret ALLOWED_HOSTS     "same as DOMAIN"
  prompt_secret PROD_ORIGIN       "https://DOMAIN"
  prompt_secret POSTGRES_USER     "postgres username (e.g. veent)"
  prompt_secret POSTGRES_PASSWORD "postgres password"
  prompt_secret GROQ_API_KEY      "Groq API key (gsk_...)"
  prompt_secret CRM_INGEST_URL    "CRM ingest endpoint URL"
  prompt_secret CRM_INGEST_SECRET "CRM ingest secret"
  prompt_secret DATAIMPULSE_USER  "DataImpulse username"
  prompt_secret DATAIMPULSE_PASS  "DataImpulse password"
  prompt_secret PLACES_API_KEY    "Google Places API key"
  prompt_secret ALLEVENTS_API_KEY "AllEvents API key"
}

# ── GitHub Actions variables (visible, non-sensitive) ─────────────────────────
sync_variables() {
  info "Setting Actions variables..."
  if gh variable set REPO_URL    --body "https://github.com/$REPO.git" --repo "$REPO" 2>> "$LOG_FILE"; then
    success "REPO_URL set"
  else
    error "REPO_URL FAILED"
  fi
  if gh variable set DEPLOY_PATH --body "/opt/veent" --repo "$REPO" 2>> "$LOG_FILE"; then
    success "DEPLOY_PATH set"
  else
    error "DEPLOY_PATH FAILED"
  fi
}

# ── Run ───────────────────────────────────────────────────────────────────────
info "Starting secret sync → $REPO (mode: $MODE)"
info "Log file: $LOG_FILE"

case "$MODE" in
  cookies)
    sync_cookies
    ;;
  infra)
    sync_defaults
    sync_interactive
    sync_variables
    ;;
  all)
    sync_cookies
    sync_defaults
    sync_interactive
    sync_variables
    ;;
esac

echo ""
if [ "$ERRORS" -gt 0 ]; then
  warn "Completed with $ERRORS error(s) — check $LOG_FILE for details"
  exit 1
else
  info "All secrets synced successfully"
  info "Push to main to trigger a deploy"
fi
