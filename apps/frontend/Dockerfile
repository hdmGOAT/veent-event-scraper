# syntax=docker/dockerfile:1

# SvelteKit operational dashboard: auth gate + reverse proxy to Django.
#
# Build context is the REPO ROOT (see docker-compose.yml) so the pnpm workspace
# lockfile is available for a reproducible `--frozen-lockfile` install, matching
# CI. The Node adapter emits a self-contained server under build/, so the
# runtime stage needs no node_modules.
FROM node:22-slim AS builder

ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN corepack enable

WORKDIR /app

# Workspace manifests first (layer caching). All apps/* package.json files are
# needed so pnpm can resolve the workspace before installing.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/backend/package.json apps/backend/
COPY apps/frontend/package.json apps/frontend/
COPY apps/n8n/package.json apps/n8n/
COPY apps/ollama/package.json apps/ollama/
RUN pnpm install --frozen-lockfile

# Frontend source + production build.
COPY apps/frontend apps/frontend
RUN pnpm --filter frontend build

# ── Runtime ──────────────────────────────────────────────────────────────────
FROM node:22-slim AS runner

ENV NODE_ENV=production \
    PORT=3000
WORKDIR /app

COPY --from=builder /app/apps/frontend/build ./build

EXPOSE 3000
CMD ["node", "build/index.js"]
