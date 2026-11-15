-- Nightly cost-history refresh.
--
-- The cost-history page is computed Python (four cost layers, including a
-- self-use battery simulation), so it cannot be a SQL job. This pokes the
-- backend to recompute a rolling window instead — one implementation of the
-- maths, no TS/SQL duplicate to drift.
--
-- Cadence: 06:35 UTC daily. Deliberately inside keep_backend_warm's window
-- (06:20-22:55 local) so the free-tier instance is already awake; a 3am run
-- would pay a 30-60s cold start on every execution.
--
-- Why a 7-day window rather than "yesterday": supplier half-hourly readings
-- settle late and can be revised for a couple of days. Recomputing a week makes
-- late arrivals self-healing. Upsert on (site_id, day), so it is idempotent.
--
-- Auth: x-internal-key must equal the backend's INTERNAL_API_KEY (the same
-- shared secret the Edge Functions already use).
--
-- SECURITY DEBT: this embeds INTERNAL_API_KEY in plaintext in cron.job, the same
-- class of debt as CRON_SECRET in optimise_and_push.sql. This key only authorises
-- internal maintenance endpoints on our own backend. Move to Supabase Vault when
-- convenient.
--
-- Apply: substitute __INTERNAL_API_KEY__ with the real value. Do NOT commit it.
-- Idempotent.

select cron.unschedule('refresh_cost_history')
where exists (select 1 from cron.job where jobname = 'refresh_cost_history');

select cron.schedule(
  'refresh_cost_history',
  '35 6 * * *',
  $job$
  select net.http_post(
    url := 'https://home-battery-optimisation.onrender.com/internal/refresh-cost-history?days=7',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'x-internal-key', '__INTERNAL_API_KEY__'
    ),
    body := '{}'::jsonb,
    timeout_milliseconds := 180000
  ) as request_id;
  $job$
);

-- Verify:
--   select jobid, jobname, schedule, active from cron.job where jobname = 'refresh_cost_history';
-- Recent responses (pg_net keeps ~6h):
--   select id, status_code, timed_out, created from net._http_response order by created desc limit 10;
-- Remove:
--   select cron.unschedule('refresh_cost_history');
