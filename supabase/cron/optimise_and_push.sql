-- Auto-push the optimised battery schedule every 30 minutes through the waking
-- window, so Tom never has to press a button while away.
--
-- Cadence: every 30 min, guarded to 06:30-22:50 Europe/London. The last run
-- (~22:30) carries published day-ahead prices and covers overnight charging, so
-- there is no need to wake the (sleeping) Render backend at 3am. The window
-- matches keep_backend_warm, so the backend is always warm when this fires.
--
-- Auth: the function deploys with --no-verify-jwt (pg_cron cannot present a JWT
-- the gateway will verify), so it enforces its own shared secret: the
-- `x-cron-secret` header must equal the function's CRON_SECRET env var. Set it
-- with `supabase secrets set CRON_SECRET=<random>` before deploying.
--
-- SECURITY DEBT: this embeds CRON_SECRET in plaintext in cron.job (same class of
-- debt as the service-role JWTs in the other jobs). The secret only authorises
-- triggering this one function, which is a much smaller blast radius than a
-- service-role JWT. Move to Supabase Vault when convenient.
--
-- Apply: substitute __CRON_SECRET__ with the real value. Do NOT commit the real
-- value; this file is the template.
--
-- Idempotent.

select cron.unschedule('schedule_optimise_and_push')
where exists (select 1 from cron.job where jobname = 'schedule_optimise_and_push');

select cron.schedule(
  'schedule_optimise_and_push',
  '*/30 * * * *',
  $job$
  select
    net.http_post(
      url := 'https://zkvnngijbostksjhkkdf.supabase.co/functions/v1/optimise-and-push',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'x-cron-secret', '__CRON_SECRET__'
      ),
      body := '{}'::jsonb,
      timeout_milliseconds := 120000
    ) as request_id
  where (now() at time zone 'Europe/London')::time
        between time '06:30' and time '22:50';
  $job$
);

-- Verify:
--   select jobid, jobname, schedule, active from cron.job where jobname = 'schedule_optimise_and_push';
-- Recent responses (pg_net keeps ~6h):
--   select id, status_code, timed_out, created from net._http_response order by created desc limit 10;
-- Remove:
--   select cron.unschedule('schedule_optimise_and_push');
