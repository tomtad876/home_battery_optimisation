# Backtest harness

Measures whether a change to the optimiser actually saves money, against real
history, before it goes anywhere near the inverter. This is the "measure first"
tool the smarter-battery ladder asks for.

## Quick start

```bash
# one-off: pull prices + demand + PV from the DB into two CSVs
./venv/bin/python scripts/backtest/prep.py

# compare strategies
./venv/bin/python scripts/backtest/backtest.py
./venv/bin/python scripts/backtest/backtest.py --strategies baseline,curve
./venv/bin/python scripts/backtest/backtest.py --pv-mode persistence
./venv/bin/python scripts/backtest/backtest.py --start 2026-06-01 --end 2026-08-31
```

`prep.py` needs `DATABASE_URL` (and `psycopg2`). It converts the FoxESS timestamps
(device-local, naive Europe/London) to UTC and resamples the 5-minute samples to
half-hourly kWh, so demand/PV line up with the UTC Agile prices.

## Method

Walk forward one day at a time. For each day the optimiser gets the forecast it
would really have had:

- **demand** — the 7-day trailing average by half-hour-of-day (exactly the app's
  method, so the forecast error is real, not assumed)
- **PV** — actual (`--pv-mode actual`, optimistic) or yesterday's
  (`persistence`, a naive errorful forecast)
- **prices** — actual Agile (published day-ahead, so realistic)
- **curve bounds** — trailing 90-day P90 import / P10 export (no look-ahead)

The plan is then **executed against the actuals**, with the inverter's behaviour:
ForceCharge takes the planned charge, ForceDischarge takes the commanded rate,
SelfUse meets actual demand (or absorbs PV surplus) and never goes below the
floor. The energy balance closes every slot:

    grid = demand − pv + charge − discharge

SOC carries across days. Results are compared with a **block bootstrap** (7-day
blocks) so the confidence interval respects day-to-day correlation.

## Adding a strategy

Add a function to `STRATEGIES` in `backtest.py`:

```python
def my_change(inputs, soc_pct, bounds):
    plan = mvp_cost_minimiser(inputs.iloc[:96], battery_capacity_kwh=CAP,
                              initial_soc_pct=soc_pct, min_soc_pct=FIXED_FLOOR,
                              max_soc_pct=100.0, ...your args...)
    return plan, FIXED_FLOOR   # (plan, execution floor)
```

`inputs` is a 72h frame; slice `[:96]` for a 48h view.

## Built-in strategies

| name | what |
|---|---|
| `baseline` | flat 20% floor + flat salvage (today) |
| `reserve` | price-aware reserve (PR #26) — backtested negative, kept as a control |
| `curve` | concave terminal value curve (Stage 3) |
| `banking` | 72h horizon (Stage 3) |
| `banking_curve` | 72h + value curve |

## Results so far (234 days, 2026-03-01 → 2026-10-20)

| strategy | saving £/day | 95% CI | verdict |
|---|---|---|---|
| `reserve` | −0.114 | −0.145 … −0.083 | **costs money** |
| `curve` | −0.001 | −0.001 … +0.002 | neutral |
| `banking` (72h) | −0.001 | −0.002 … +0.003 | neutral |
| `banking_curve` | −0.001 | −0.002 … +0.003 | neutral |

Same picture with `--pv-mode persistence`. The LP is already close to optimal
over its visible horizon: the reserve over-constrains, and the value curve /
longer horizon don't change the decisions enough to beat the noise. The genuinely
additive work is a *new* flexible load (Stage 2, hot water) or correctness fixes
(e.g. the telemetry timezone), not more objective tuning.

## Caveats

- Daily solve, not the real 30-minute rolling re-solve. The mechanism is per-slot,
  so it shouldn't change a sign, but a rolling mode would be more faithful.
- Prices are perfect (day-ahead). In production the tail beyond ~24-36h is
  synthetic, so a 72h horizon sees an estimate for day 3 — the backtest's 72h
  result is therefore an *optimistic* upper bound.
- Only ~24 days of real SoC history exist; the SOC here is simulated, not measured.
