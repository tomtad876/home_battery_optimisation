# Migration from In-App Scheduler to Supabase Edge Functions

## Summary

We've moved scheduled data collection (Solcast, Agile prices, demand forecasts) out of the FastAPI backend and into **Supabase Edge Functions** (serverless functions running close to the DB).

**Benefits:**
- ✅ Main API process no longer carries scheduling overhead
- ✅ Runs close to the database (lower latency, better reliability)
- ✅ Independent scaling (scheduler failures don't crash the API)
- ✅ Better rate-limit handling (retry logic inside the function)
- ✅ Easier to debug and monitor (Supabase logs are separate)

## What Changed

### Removed
- `app/tasks/scheduler.py` — in-app APScheduler implementation
- `apscheduler` dependency from `requirements.txt`
- Scheduler lifecycle hooks from `app/main.py`

### Added
- `supabase/functions/fetch-solcast/` — fetch and store Solcast forecasts
- `supabase/functions/fetch-agile-prices/` — fetch and store Octopus Agile prices
- `supabase/functions/fetch-demand/` — fetch and store 7-day demand profile
- `supabase/migrations/001_add_scheduled_data_collection.sql` — DB schema updates
- `supabase/functions/README.md` — deployment and operations guide

## Deployment Steps

### 1. Install Supabase CLI
```bash
npm install -g supabase
# or
brew install supabase/tap/supabase
```

### 2. Set up Supabase project secrets
In Supabase Dashboard → Project Settings → Secrets:
```
SOLCAST_API_KEY = <your-key>
SOLCAST_PV_SYSTEM_ID = <your-system-id>
FOXESS_API_KEY = <your-key>
```

### 3. Deploy Edge Functions
```bash
cd supabase/functions

supabase functions deploy fetch-solcast
supabase functions deploy fetch-agile-prices
supabase functions deploy fetch-demand
```

Verify deployment:
```bash
supabase functions list
```

### 4. Run SQL migrations
Open Supabase SQL Editor and run:
```sql
-- Copy contents from supabase/migrations/001_add_scheduled_data_collection.sql
```

Or via CLI (if using local Supabase):
```bash
supabase db push
```

### 5. Set up scheduling
**Option A: Supabase Scheduler (Recommended)**
In Supabase Dashboard → Edge Functions → (function name) → Scheduling tab:
- `fetch-solcast`: Run every 90 minutes between 07:00–22:00 (10 slots)
  - Times: 07:00, 08:30, 10:00, 11:30, 13:00, 14:30, 16:00, 17:30, 19:00, 20:30
- `fetch-agile-prices`: Run daily at 16:00 UTC (with retry at 16:15, 16:30)
- `fetch-demand`: Run daily at 03:00 UTC

**Option B: External Scheduler (GitHub Actions, Cloud Scheduler, etc.)**
Create a cron job that POSTs to the Edge Function URL:
```bash
curl -X POST https://<project-id>.supabase.co/functions/v1/fetch-solcast \
  -H "Authorization: Bearer <anon-key>" \
  -H "Content-Type: application/json"
```

### 6. Update the main API to query from DB instead of external APIs

In `app/services/forecast.py`, modify `forecast_solar_and_prices()` to query the DB:
```python
from app.core.database import SessionLocal
from app.models.forecast import ForecastInterval

def forecast_solar_and_prices(pv_system_id: str | None = None) -> pd.DataFrame:
    """Query latest forecast from DB instead of calling external APIs."""
    session = SessionLocal()
    intervals = session.query(ForecastInterval).filter(
        ForecastInterval.solar_kwh.isnot(None) | ForecastInterval.import_price.isnot(None)
    ).order_by(ForecastInterval.period_end).all()
    session.close()
    
    # Convert to DataFrame
    data = [{
        'PeriodEnd': i.period_end,
        'PvEstimate': i.solar_kwh,
        'price': i.import_price * 100 if i.import_price else None  # convert £ to pence
    } for i in intervals]
    return pd.DataFrame(data)
```

Similarly, update `forecast_demand_last_week_avg()` to query the DB (or compute on-the-fly from the 48 stored demand values).

## Monitoring

Check data freshness in Supabase:
```sql
SELECT source_type, MAX(fetched_at) as last_update, COUNT(*) as record_count
FROM forecast_runs
WHERE status = 'success'
GROUP BY source_type;
```

View recent errors:
```sql
SELECT source_type, error_message, COUNT(*) as count
FROM forecast_failures
WHERE failed_at > NOW() - INTERVAL '7 days'
GROUP BY source_type, error_message;
```

## Testing Locally

```bash
# Start Supabase locally
supabase start

# Copy .env secrets to supabase local
# Then invoke a function manually
supabase functions invoke fetch-solcast --local

# Check logs
supabase functions get-logs fetch-solcast --limit 50
```

## Troubleshooting

### "Function not found" error
- Ensure function is deployed: `supabase functions list`
- Check function name matches exactly: `fetch-solcast`, `fetch-agile-prices`, `fetch-demand`

### API errors when calling FoxESS or Solcast
- Verify API keys in Supabase Secrets are correct
- Check API key permissions (especially FoxESS and Solcast accounts)
- Look at function logs: `supabase functions get-logs <function-name>`

### Duplicate rows in `forecast_intervals`
- Ensure SQL migration ran (adds unique index on `period_end`)
- Check that upserts are working: `SELECT * FROM forecast_intervals WHERE period_end = '2026-02-22T15:30:00Z';`

### Data not appearing in DB
- Verify `forecast_runs` table is being written to: `SELECT * FROM forecast_runs ORDER BY fetched_at DESC LIMIT 5;`
- Check `status` column (should be 'success')
- Look at function invocation logs

## Next Steps

- [ ] Implement DB querying in `app/services/forecast.py`
- [ ] Update API endpoint `/optimise/mvp` to query stored data instead of live API calls
- [ ] Add `/admin/refresh-forecast` endpoint to manually trigger Edge Functions on-demand
- [ ] Set up alerts/webhooks for repeated function failures
- [ ] Add analytics dashboard showing data freshness and collection stats
- [ ] Extend to multi-site support (store `site_id` with each forecast run)

## Rollback

If you need to revert to the in-app scheduler:
1. Restore `app/tasks/scheduler.py` from git history
2. Restore `app/main.py` with scheduler lifecycle hooks
3. Restore `apscheduler` to `requirements.txt`
4. Delete Edge Functions (or leave them as backup)

```bash
supabase functions delete fetch-solcast
supabase functions delete fetch-agile-prices
supabase functions delete fetch-demand
```
