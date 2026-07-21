#!/usr/bin/env bash
# Bootstrap a fresh VM for veent-event-scraper.
# Run once — safe to re-run (idempotent).
#
# Usage:
#   ./setup.sh <repo-url> [deploy-path]
#
# Example:
#   ./setup.sh https://github.com/your-org/veent-event-scraper.git /opt/veent
#
# After this runs:
#   1. Copy cookie files into <deploy-path>/cookies/
#      (facebook.json, instagram.txt — see .env.example for var names)
#   2. Push to main — GitHub Actions writes .env and starts the stack.

set -euo pipefail

REPO_URL="${1:?Usage: $0 <repo-url> [deploy-path]}"
DEPLOY_PATH="${2:-/opt/veent}"

# ── Docker ────────────────────────────────────────────────────────────────────
if command -v docker &>/dev/null; then
  echo "Docker already installed — skipping."
else
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi

# ── Repo ──────────────────────────────────────────────────────────────────────
if [ -d "$DEPLOY_PATH/.git" ]; then
  echo "Repo already cloned at $DEPLOY_PATH — updating remote to $REPO_URL."
  git -C "$DEPLOY_PATH" remote set-url origin "$REPO_URL"
else
  echo "Cloning $REPO_URL → $DEPLOY_PATH"
  git clone "$REPO_URL" "$DEPLOY_PATH"
fi

# ── Cookies dir ───────────────────────────────────────────────────────────────
mkdir -p "$DEPLOY_PATH/cookies"
echo "Cookies directory ready at $DEPLOY_PATH/cookies"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "Setup complete."
echo ""
echo "Next steps:"
echo "  1. Add cookie files to $DEPLOY_PATH/cookies/"
echo "     (facebook.json and instagram.txt — see .env.example)"
echo "  2. Push to main — GitHub Actions will write .env and start the stack."
echo ""
echo "  Deploy path: $DEPLOY_PATH"
echo "  Repo origin: $REPO_URL"
