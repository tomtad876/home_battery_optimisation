-- Add an afternoon run of fetch-agile-prices at 16:30 UTC (17:30 BST).
--
-- Why: the upstream Agile feed (agilerates.uk) recomputes its D+1 rates around
-- 16:00 UTC. The existing runs (11:15 / 17:15 / 18:15 UTC) leave no refresh
-- between 12:15 and 18:15 BST, so agile_rates goes stale every afternoon and
-- ~89% of the 48 h plan is built on synthetic (7-day average) prices.
-- 16:30 UTC is the first run after the feed recompute.
--
-- Deliberately one extra run for now; cadence may increase later.
--
-- Idempotent, and deliberately does NOT embed the service-role JWT: it reuses
-- the command already stored on `schedule_agile_prices`. See ../CRON.md.

select cron.unschedule('schedule_agile_prices_pm')
where exists (select 1 from cron.job where jobname = 'schedule_agile_prices_pm');

select cron.schedule(
  'schedule_agile_prices_pm',
  '30 16 * * *',
  (select command from cron.job where jobname = 'schedule_agile_prices')
);

-- Revert:
--   select cron.unschedule('schedule_agile_prices_pm');
