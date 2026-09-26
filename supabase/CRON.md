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
| `schedule_agile_prices` | 3 | `30 11,15,17,18 * * *` | 12:30 / **16:30** / 18:30 / 19:30 | `fetch-agile-prices` |
| `schedule_historic_energy_data` | 8 | `*/15 * * * *` | every 15 min | `fetch-demand` |
| `schedule_heat_pump` | 9 | `*/15 * * * *` | every 15 min | `fetch-heatpump` |
| `keep_backend_warm` | — | `*/10 5-22 * * *` | 06:20–22:55 (London guard) | Render `/health` |

Job ids are assigned by `cron.schedule` and are only indicative here. There is
deliberately **no** separate afternoon job — the 16:30 local run lives on the
existing `schedule_agile_prices` job.

`keep_backend_warm` is the exception to "all schedules are UTC": its cron
expression is UTC but the window is enforced by a **Europe/London guard inside
the command**, so it follows BST/GMT. See below.

## Why the 16:30 local Agile run (added 2026-09-23)

The upstream Agile feed (`agilerates.uk`) recomputes its D+1 rates around
**16:00 UTC**. The original runs at 11:15 / 17:15 / 18:15 UTC leave no refresh
between 12:15 and 18:15 BST, so `agile_rates` went stale every afternoon: only
~11 of the 96 horizon slots were real, and ~89% of the 48 h plan was built from
the 7-day time-of-day average ("typical day") prices.

A run at **16:30 local (15:30 UTC while BST)** sits just after the feed
recompute and before the end of the working day, so the plan is refreshed for
the rest of the afternoon.

It is folded into the **existing** `schedule_agile_prices` job rather than a
separate one. A cron expression has a single minute field, so the original
`:15` runs moved to `:30`; the hours are otherwise unchanged apart from the new
15:00 UTC run. Deliberately a single extra run for now — cadence can increase
later (original suggestion was `*/30 10-21 * * *`).

**DST caveat:** the schedule is fixed UTC, so "16:30 local" only holds while
BST is in force. When BST ends (late Oct) it becomes 15:30 local unless the
schedule is shifted by an hour.

Apply / revert: [`cron/agile_fetch_schedule.sql`](cron/agile_fetch_schedule.sql).

## Why `keep_backend_warm` (added 2026-09-26)

Render's free tier spins a web service down after 15 minutes with no inbound
traffic; the next request pays a ~30-60s cold start. A ping every 10 minutes
keeps the backend resident through the hours the app is actually used, so the
dashboard and an ad-hoc re-run are always instant. It costs no money and no
Edge Function — just a direct `pg_net` GET to the unauthenticated `/health`.

**Waking hours, DST-correct.** The job fires every 10 minutes between 05:00 and
22:59 UTC but the command only pings when local time is **06:20–22:55**
(`now() at time zone 'Europe/London'`). This is because pg_cron 1.6.4 has no
per-job timezone (`cron.schedule_in_timezone` doesn't exist here) and changing
the global `cron.timezone` would shift every other job. The guard makes the
window follow BST/GMT automatically. The first ping lands ~10 min before 06:30
(so it's warm *by* then) and the last holds it warm until ~23:05.

**Instance hours:** with sleeping enforced overnight this uses ~18h/day
(~540h/month) of Render's 750 free instance hours — comfortably inside the cap.
Pinging 24/7 would also fit (~720h) but leave no headroom.

Apply / revert: [`cron/keep_backend_warm.sql`](cron/keep_backend_warm.sql).

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
