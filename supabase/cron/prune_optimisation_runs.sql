-- Retention for persisted optimiser runs.
--
-- Persisting a run costs ~96 interval rows, and the auto-push cron runs every
-- 30 minutes through waking hours (~33 runs/day), so a single site generates
-- roughly 3.2k interval rows per day. That is trivial for Postgres, but it is
-- unbounded growth for data whose only use is recent comparison and scoring —
-- nobody needs last quarter's plans half-hourly.
--
-- The FKs are set up for this (migration e1f2a3b4c5d6):
--   * optimisation_intervals.optimisation_run_id  ON DELETE CASCADE
--   * schedules.optimisation_run_id               ON DELETE SET NULL
-- so deleting a run removes its intervals and leaves the push audit row (the
-- groups actually sent) intact with a null link. Runs referenced by a schedule
-- are NOT kept — keeping them would have made every pushed run immortal, which
-- is every run.
--
-- Keeps 90 days. Runs nightly at 03:30 UTC (cheap hours, far from the push
-- cadence).
--
-- Idempotent.

select cron.unschedule('prune_optimisation_runs')
where exists (select 1 from cron.job where jobname = 'prune_optimisation_runs');

select cron.schedule(
  'prune_optimisation_runs',
  '30 3 * * *',
  $job$
  delete from optimisation_runs
  where created_at < now() - interval '90 days';
  $job$
);

-- Verify:
--   select jobid, jobname, schedule, active from cron.job where jobname = 'prune_optimisation_runs';
-- One-off check of what would be pruned:
--   select count(*) from optimisation_runs where created_at < now() - interval '90 days';
-- Remove:
--   select cron.unschedule('prune_optimisation_runs');
