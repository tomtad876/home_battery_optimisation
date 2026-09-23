-- Add an afternoon run of fetch-agile-prices to the EXISTING job
-- (`schedule_agile_prices`, job 3) rather than a separate job.
--
-- Target: 16:30 Europe/London (currently BST = 15:30 UTC), just after the
-- upstream feed's ~16:00 UTC recompute.
--
-- Why the minute changes: one cron expression has a single minute field, so
-- adding a :30 run means the existing :15 runs move to :30. Hours are
-- otherwise unchanged except for the new 15:00 UTC (16:30 BST) run.
--
-- Idempotent. Embeds no secret - only the schedule changes.

-- 1. Drop the separate afternoon job if a previous version created it.
select cron.unschedule('schedule_agile_prices_pm')
where exists (select 1 from cron.job where jobname = 'schedule_agile_prices_pm');

-- 2. Fold the afternoon run into the existing job.
--    15:30 UTC = 16:30 BST.
select cron.alter_job(
  (select jobid from cron.job where jobname = 'schedule_agile_prices'),
  schedule => '30 11,15,17,18 * * *'
);

-- Note: the database timezone is UTC, so 15:30 UTC is 16:30 local only while
-- BST is in force. When BST ends (late Oct) it becomes 15:30 local unless the
-- schedule is shifted by an hour.

-- Revert to the original schedule:
--   select cron.alter_job(
--     (select jobid from cron.job where jobname = 'schedule_agile_prices'),
--     schedule => '15 11,17,18 * * *'
--   );
