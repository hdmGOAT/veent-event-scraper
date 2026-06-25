# Veent Event Scraper — Docs

| Doc | What it covers |
|---|---|
| [n8n-webhook-endpoints.md](n8n-webhook-endpoints.md) | Django webhook endpoints, auth setup, `.env`, code changes made |
| [n8n-scraper-automation-workflow.md](n8n-scraper-automation-workflow.md) | Scheduled workflow that runs all 8 Django scrapers via n8n |
| [n8n-ai-event-scraper.md](n8n-ai-event-scraper.md) | AI-powered scraper using Jina Reader + GPT-4o (Lu.ma; cloneable for other sites) |
| [n8n-leads-sheets-sync.md](n8n-leads-sheets-sync.md) | Async **upsert** of `/api/events/` (by `db_id`) into the `Events Sync` Google Sheets tab — formats `event_date`, computes `event_status`, preserves human/CRM columns; no scraping |

## Quick start

1. Set `SCRAPER_WEBHOOK_SECRET` in `.env`
2. Expose Django: `ngrok http 8000`
3. Update the Django URL in each n8n workflow's HTTP Request nodes
4. Activate the workflows in n8n

## n8n workflow URLs

| Workflow | URL |
|---|---|
| Veent Scraper Automation | https://jsrl.app.n8n.cloud/workflow/QVedq95qV8EkOiuE |
| AI Event Scraper: Lu.ma | https://jsrl.app.n8n.cloud/workflow/yFwdijIjegInX2Lt |
