# Supabase Edge Functions for Scheduled Data Collection

This folder contains Supabase Edge Functions to fetch Solcast forecasts, Octopus Agile prices, and demand profiles on a schedule, storing results directly in Supabase without hitting the main API.

## Functions

### `fetch-solcast` (Solcast Solar Forecasts)
- **Trigger**: Every 1.5 hours between 07:00–22:00 (10 calls/day max for free tier)
- **Schedule (cron)**: `0 7 * * *` → `22 * * * *` (staggered via Cloud Scheduler or Supabase cron)
- **Input**: Environment variables
  - `SOLCAST_API_KEY`
  - `SOLCAST_PV_SYSTEM_ID`
  - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- **Output**: Writes to `forecast_runs` (source_type='solcast') and `forecast_intervals` (solar_kwh values)
- **Idempotency**: Skips if last run was < 5 minutes ago

### `fetch-agile-prices` (Octopus Agile Tariff)
- **Trigger**: Daily around 16:00–16:30 (prices published ~16:00 UK time)
- **Schedule (cron)**: `0 16 * * *` with retry at 16:15, 16:30 if initial fetch fails
- **Input**: Environment variables
  - `FOXESS_API_KEY`
  - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- **Output**: Writes to `forecast_runs` (source_type='agile_prices') and `forecast_intervals` (import_price values)
- **Coverage**: 11pm today → 11pm tomorrow (24-hour rolling window)
- **Idempotency**: Skips if last run was < 1 hour ago

### `fetch-demand` (7-Day Average Demand Profile)
- **Trigger**: Daily at 03:00
- **Schedule (cron)**: `0 3 * * *`
- **Input**: Environment variables
  - `FOXESS_API_KEY` (to call load history endpoint)
  - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- **Output**: Writes to `forecast_runs` (source_type='demand_forecast') and `forecast_intervals` (demand_kwh values for next 48 half-hours)
- **Idempotency**: Skips if last run was < 1 hour ago

## Deployment

### Prerequisites
- Supabase CLI installed: https://supabase.com/docs/guides/cli
- Local `.env` with Supabase credentials
- FoxESS and Solcast API keys configured in Supabase Secrets

### Step 1: Add Environment Variables in Supabase

In Supabase Dashboard → Project Settings → Secrets:
```
SOLCAST_API_KEY = your-key
SOLCAST_PV_SYSTEM_ID = your-id
FOXESS_API_KEY = your-key
```

### Step 2: Deploy Functions

```bash
cd supabase/functions

# Deploy all functions
supabase functions deploy fetch-solcast
supabase functions deploy fetch-agile-prices
supabase functions deploy fetch-demand
```

### Step 3: Set Up Scheduled Execution

In Supabase Dashboard → Edge Functions → (select function) → Scheduling (or use Supabase Scheduler):

**Option A: Supabase Scheduler (if available)**
Create cron jobs in Supabase's scheduler UI:
- `fetch-solcast`: Run every 1.5 hours 07:00–22:00
- `fetch-agile-prices`: Run daily at 16:00 (+ retries at 16:15, 16:30)
- `fetch-demand`: Run daily at 03:00

**Option B: External Scheduler (GitHub Actions, Cloud Scheduler, etc.)**
Create a workflow that calls the Edge Function URL:
```bash
# Example: GitHub Actions runs daily at 16:00 UTC
curl -X POST https://<project>.supabase.co/functions/v1/fetch-agile-prices \
  -H "Authorization: Bearer <anon-key>" \
  -H "Content-Type: application/json"
```

### Step 4: Run SQL Migrations

In Supabase SQL Editor, paste and run the contents of:
```
supabase/migrations/001_add_scheduled_data_collection.sql
```

This creates:
- New columns: `source_type`, `fetched_at`, `status` on `forecast_runs`
- Indexes for efficient lookups and upserts
- Views: `latest_forecast`, `current_forecast` for querying the latest data
- Table: `forecast_failures` for tracking errors

## Testing Locally

```bash
# Start Supabase locally
supabase start

# Run a function locally
supabase functions invoke fetch-solcast --local

# Check logs
supabase functions get-logs fetch-solcast
```

## Monitoring & Alerts

- Check `forecast_runs` table for `status='success'` and recent `fetched_at` timestamps
- Monitor `forecast_failures` table for repeated errors
- (Optional) Add webhook alerts to Slack/Discord on function failures using Supabase's HTTP webhooks

## Future Enhancements

- Multi-site support: accept `site_id` as input parameter and store per-site forecasts
- Retry logic with exponential backoff on temporary failures
- Compression of old forecast runs (archive > 30 days)
- Validation of data quality before writing (e.g., price sanity checks)
- Analytics dashboard showing data freshness and API usage

## Architecture Notes

- Edge Functions run in Deno (TypeScript/JavaScript) close to the DB
- Upserts use `period_end` as conflict key to avoid duplicates across multiple function runs
- The main API (`app/api/routes.py`) will query `current_forecast` view instead of calling external APIs
- Each function is independent and idempotent (safe to call multiple times)
