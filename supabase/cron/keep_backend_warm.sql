-- Keep the Render backend warm during waking hours.
--
-- Render's free tier spins a web service down after 15 minutes with no inbound
-- traffic; the next request pays a ~30-60s cold start (container boot + Python
-- + cvxpy import). Pinging /health every 10 minutes keeps the process resident,
-- so the dashboard and an ad-hoc re-run never wait for a wake-up.
--
-- Why not an Edge Function: /health is unauthenticated, so this is a direct
-- pg_net GET. Wrapping it in a function would add a hop, another deploy, and
-- another plaintext service-role JWT in cron.job for no benefit.
--
-- Why the WHERE clause: pg_cron 1.6.4 (this project) has no per-job timezone
-- (cron.schedule_in_timezone does not exist) and changing the global
-- cron.timezone would shift every other job. So the job fires every 10 minutes
-- and the command itself decides whether we're inside the waking window,
-- evaluated in Europe/London -- which tracks BST/GMT automatically.
--
-- Window 06:20-22:55 local: the first ping lands ~10 min before 06:30 so the
-- instance is warm *by* the time it's used, and the last (22:50) holds it warm
-- until ~23:05. The enclosing UTC hour range (5-22) just trims no-op overnight
-- runs; the guard does the precise trimming.
--
-- Idempotent.

select cron.unschedule('keep_backend_warm')
where exists (select 1 from cron.job where jobname = 'keep_backend_warm');

select cron.schedule(
  'keep_backend_warm',
  '*/10 5-22 * * *',
  $job$
  select net.http_get(
    url := 'https://home-battery-optimisation.onrender.com/health',
    timeout_milliseconds := 70000
  ) as request_id
  where (now() at time zone 'Europe/London')::time
        between time '06:20' and time '22:55';
  $job$
);

-- Verify the job exists:
--   select jobid, jobname, schedule, active from cron.job where jobname = 'keep_backend_warm';
-- Inspect recent pings (pg_net keeps responses ~6h):
--   select id, status_code, timed_out, created from net._http_response order by created desc limit 10;
-- Remove:
--   select cron.unschedule('keep_backend_warm');
