# Scheduled jobs (pg_cron)

Source of truth for the `pg_cron` jobs that drive the Edge Functions. These
schedules live in the Supabase database (`cron.job`), **not** in code, so this
file is the record of what should be there — check it against the DB when in
doubt.

All schedules are **UTC** (the Supabase database timezone is `UTC`).
BST = UTC+1 (late March → late October).

| Job name | id | Schedule (UTC) | Local (BST) | Function |
|---|---|---|---|---|
| `schedule_solcast` | 1 | `*/90 7-21 * * *` | 08:00–22:00 | `fetch-solcast` |
| `schedule_agile_prices` | 3 | `15 11,17,18 * * *` | 12:15 / 18:15 / 19:15 | `fetch-agile-prices` |
| `schedule_agile_prices_pm` | 10 | `30 16 * * *` | 17:30 | `fetch-agile-prices` |
| `schedule_historic_energy_data` | 8 | `*/15 * * * *` | every 15 min | `fetch-demand` |
| `schedule_heat_pump` | 9 | `*/15 * * * *` | every 15 min | `fetch-heatpump` |

Job ids are assigned by `cron.schedule` and are only indicative here.

## Why the 16:30 UTC Agile run (added 2026-09-22)

The upstream Agile feed (`agilerates.uk`) recomputes its D+1 rates around
**16:00 UTC**. The original runs at 11:15 / 17:15 / 18:15 UTC leave no refresh
between 12:15 and 18:15 BST, so `agile_rates` went stale every afternoon: only
~11 of the 96 horizon slots were real, and ~89% of the 48 h plan was built from
the 7-day time-of-day average ("typical day") prices. 16:30 UTC is the first
run *after* the feed recompute, so it reliably captures tomorrow's published
prices before the evening runs.

Deliberately a single extra run for now — cadence can increase later (the
original suggestion was `*/30 10-21 * * *`).

Apply / revert: [`cron/agile_afternoon.sql`](cron/agile_afternoon.sql).

## Gotchas

- **`succeeded` in `cron.job_run_details` is meaningless.** The jobs call
  `net.http_post`, which is fire-and-forget — the job logs success regardless
  of what the Edge Function returned. This is the silent-failure mode behind
  the 2026-09-13 incident (a `fetch-agile-prices` 401 went unnoticed for days).
  To detect real failures, have the function write a `fetch_runs` row and alert
  on zero rows. (Known follow-up, not yet built.)
- **Edge Functions must deploy with `--no-verify-jwt`** (`supabase/deploy.sh`)
  because the cron command sends a legacy HS256 service-role JWT.
- **Security debt:** each job's command embeds a service-role JWT in plaintext
  in `cron.job` — anyone with DB read access can lift it. Rotate and move to
  Supabase Vault. Do **not** copy the token into the repo; the apply script
  reuses the existing job's command instead.
