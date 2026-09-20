# Code review — 2026-09-19

First full-codebase review since the project went live. Run with stronger reasoning
models than the code was originally written under.

**Method:** four read-only review agents across (1) optimiser core + forecast,
(2) API/data/auth/encryption, (3) FoxESS service + Edge Functions, (4) frontend.
Every HIGH finding below was then verified directly against the source by the
orchestrating agent. Test baseline at review time: **60 passing**.

**One reviewer HIGH was rejected after verification** — see "Rejected / false
positives". Do not re-raise it.

Confidence is marked where the orchestrator did not personally read the lines:
`[verified]` = confirmed by direct read; `[reported]` = reviewer finding, not
independently re-read.

---

## Priority order

1. §2 Cold-start UX + §7 error rendering — same helper, unblocks daily use (the real #1)
2. §1 Frontend battery params — one-line deletion, latent for any non-5-kWh user (bundle with §2)
3. §3 Setup wizard credential save — prerequisite for a second user (latent; Tom uses the settings page)
4. §4 Optimiser hardening — efficiency + terminal SOC + grid bounds + delete alpha
5. §5 Classifier parity — **gate for enabling the auto-push cron**
6. §6 Auth/security hardening

---

## 1. Battery parameters hardcoded in the frontend `[verified; severity corrected 2026-09-19]`

`frontend/pages/index.js:137-143` (preview), `:178-184` (push), `:248-254`
(auto-run), and `frontend/components/OptimiserForm.js:5` all hardcode
`battery_capacity_kwh: 5.0`, `charge_power_kw: 3.0`, `discharge_power_kw: 3.0`.

**Tom's actual battery is 5 kWh**, so the hardcoded value is coincidentally
correct today and no wrong schedule has reached the device. The bugs are:

- **It's hardcoded at all.** The backend was written to use the saved battery
  row — `app/api/routes.py:348-353` ("Use battery config as defaults — don't
  hardcode") — so the frontend defeats the single source of truth. Any user
  whose battery isn't 5 kWh / 3 kW silently gets schedules computed for the
  wrong device, with no error.
- **The docs disagree.** `RUN_LOCALLY.md:65` says "Keep at 15 kWh" and
  `README.md:93`'s example body says `15.0` — both wrong for the real device and
  misleading to anyone onboarding.

**Fix:** send only what's genuinely unknown — `{ initial_soc_pct }` for the
optimise call, `{ preview: true }` / `{}` for preview and push — delete the
duplicated literals, and correct the docs (don't state a capacity in prose; point
at the settings page). Latent bug for other users, not a live money leak for Tom.

## 2. Cold-start UX — the named #1 blocker `[verified]`

- `index.js:85-89` / `handleOptimise` — bare `fetch`, no `AbortController`, no
  deadline, no retry, no distinction between "cold" and "dead".
- `index.js:59-61` (`checkSite` → `/sites/me`) — a hang here blocks the whole UI
  behind a bare "Loading..." (`:297-301`).
- `index.js:30-49` (`fetchRealtime`) — swallows failures silently; if SOC never
  arrives, the auto-run at `:245` never fires and the user sees a placeholder
  with no explanation.
- `index.js:115` surfaces raw `TypeError: failed to fetch`.

**Fix:** one shared `apiFetch` helper — `AbortController` timeout (~30s),
retry once/twice on abort/network error only (not 4xx) with ~2s backoff, honest
loading copy ("waking the server — first request after idle can take ~30–60s").
This same helper is where §7's `extractDetail` belongs.

## 3. Setup wizard never saves credentials `[verified]`

`SetupWizard.js:122-124` — `handleFinish` only calls `onComplete(siteId)`.
Step 3 collects `solcast_api_key`, `solcast_system_id`, `foxess_api_key`, then
discards them. `SetupWizard.js:77-81` writes `provider_config` from an empty
`credData` at battery-creation time.

**Impact:** a newly onboarded user finishes the wizard with no credentials.
`/optimise/push` then fails with "FoxESS credentials not configured"
(`routes.py:334-335`) and the backend never fetches forecasts. Also missing:
`foxess_device_sn`, which the push endpoint requires.

**Fix:** in `handleFinish`, `PUT /batteries/me/provider_config` with `credData`
(the endpoint merges, `routes.py:140-160`), add a `foxess_device_sn` field to
step 3, then call `onComplete`.

## 4. Optimiser hardening — `app/core/optimiser.py` `[verified]`

This is the "round-trip efficiency" next-action, plus three siblings that are
arguably higher impact. All are small and localised in the same block.

**4a. No round-trip efficiency** (`:92`, `:94`). SOC recursion is lossless:
`soc[t] == soc[t-1] + b_charge[t] - b_discharge[t]`, where the flows are AC-side
(they appear in the energy balance). Add `eta_c`/`eta_d`
(AC-coupled lithium, round-trip ≈ 0.90–0.93):

```
soc[0] == init_soc_kwh + eta_c * b_charge[0] - b_discharge[0] / eta_d
soc[t] == soc[t-1]   + eta_c * b_charge[t]   - b_discharge[t]   / eta_d
```

Objective (`:117`) and balance (`:110`) stay unchanged — keeping variables
AC-side is the clean formulation. Behaviour: the LP cycles only when
`sell_price ≥ buy_price / (eta_c * eta_d)`, i.e. the real arbitrage break-even.
`test_optimiser.py:70-76` must be updated to match; add a test that no cycling
happens when `eta_c * eta_d * sell < buy`.

**4b. No terminal SOC constraint** (nothing after `:111`). Stored energy has
zero value to the LP, so it drains to `soc_min` and discharges *initial* SOC
straight to grid at any positive export price. On a 15 kWh battery starting at
50% with min 20%, that's up to 4.5 kWh dumped at ~5p that gets re-imported next
day at ~25p. **Fix:** one line — `soc[n-1] >= min(init_soc_kwh, soc_max_kwh)`
(or a `terminal_soc_pct` param).

**4c. Grid import/export capped at battery power** (`:104-106`). Comment says
"same as battery for simplicity". Two failures: (i) infeasible when demand
exceeds the cap at min SOC (kettle + oven ≈ 4–5 kW draw is normal), and there's
no solar-curtailment variable so solar > cap is also infeasible; (ii)
economically wrong — export is silently truncated. **Fix:** add a `grid_limit_kw`
param (fuse rating, not inverter rating) and a solar spill variable in the
balance at `:110`.

**4d. `alpha` "future price incentive" term** (`:118-125`). The LP already
captures cross-period arbitrage via the SOC dynamics. This term pays the battery
to charge in any sub-horizon-max period even if the energy is never discharged,
and its bare `except Exception: pass` hides construction failures. **Delete it**
(especially once 4a lands, since it actively subsidies lossy cycling).

**4e. Initial SOC below min SOC → infeasible at t=0** (`:92` + `:97` with charge
capped at `:101`). Reachable from the API (`routes.py:257` only checks
`min < max`). **Fix:** recovery ramp —
`soc_lb[t] = min(soc_min_kwh, init_soc_kwh + t * max_batt_charge_energy)`.

**4f. Solver unconfigured** (`:128-131`). No solver pin, no timeout, and
`optimal_inaccurate` is rejected. **Fix:** pin a solver (CLARABEL/ECOS),
timeout, accept `OPTIMAL` or `OPTIMAL_INACCURATE`.

**4g. Minor:** `dt = 0.5` hardcoded (`:72`); `battery_capacity_kwh == 0` →
division by zero (`:136`); `eps = 1e-3` netting (`:143-150`) makes reported rows
violate continuity by more than the tests' `atol=1e-6`.

**Test blindness:** `tests/conftest.py:41` caps demand at 0.8 kWh — below the
1.5 kWh grid bound — so the whole suite is blind to 4c. Highest-value new tests:
demand spike at min SOC; initial < min SOC; terminal SOC; export > import price;
negative prices; missing mid-horizon price; solver failure path.

## 5. Auto-push path has diverged from the validated Python path `[verified]`

The cron path (`supabase/functions/optimise-and-push`) uses the **TypeScript**
classifier. It has drifted from the Python classifier that the manual
preview/push path exercises. Identical optimiser output ⇒ different device
behaviour.

- **5a. No per-group sizing** — `classify-schedule.ts:169-179` always uses
  full configured `maxSoc`, `fdSoc = minSoc`, `fdPwr = ratedPowerW`. Python
  (`foxess.py:289-301`) sizes each group's SOC/power to what the LP scheduled.
  `OptimiserSlot.soc_pct` / `ClassifierConfig.capacityKwh` are declared but
  unused in TS.
- **5b. Group-count headroom missing** — `classify-schedule.ts:249` merges to
  the full `maxGroups` *before* the remain-filter (`index.ts:180`) and midnight
  split (`:183`), then appends the remain group (`:188`) → can exceed
  `maxGroupCount` and be rejected. Python does filter → split → merge to
  `max_groups - 1` → append.
- **5c. Failures return HTTP 200** with `success:false` (`index.ts:220-228`) →
  pg_cron logs "succeeded". This is the exact silent-failure mode of the
  2026-09-13 incident. Also: the `schedules` audit row inserts pre-filter
  `groups` (`:206`) not `finalGroups`, and because `sendScheduleToInverter`
  throws, the `status: "failed"` branches (`:204`, `:210`) are dead.
- **5d. errno `40401` retried in Python, not in TS** — `foxess.py:357` vs
  `foxess-schedule.ts:192`.
- **5e. Merge differs in both stage and scoring** — Python `is_self_use + i`
  (`foxess.py:597-598`, earliest-first) vs TS `isSelfUse + slotCount`
  (`classify-schedule.ts:134-135`, smallest-first); and Python merges *after*
  the remain filter, TS *before*.
- **5f. Index-0 merge corrupts a group — both implementations**
  (`foxess.py:611`, `classify-schedule.ts:146`): when the candidate is index 0,
  `target = 1` and the target's **end** is set to the candidate's (earlier) end
  → end before start.
- **5g. Remain-mode detection differs** — TS infers "any 00:00–23:59 group"
  (`foxess-schedule.ts:118-125`); Python uses the `isRemainMode` flag
  (`foxess.py:328-331`). The 24h cap + midnight split can produce a genuine
  full-day non-remain group, which TS would then drop as redundant.
- **5h. Intl hour "24"** — `classify-schedule.ts:274-283` uses `hour12: false`,
  which V8/Deno can resolve to h24, emitting `startHour: 24` at midnight. Use
  `hourCycle: "h23"`.

**Gate:** add a golden parity fixture — the same 48-slot input through Python
`classify_optimiser_output` and TS `classifySchedule`, asserting identical
groups — *before* enabling the cron. **Do not enable auto-push until this
passes.** The TS side currently has zero tests.

## 6. Auth & security `[verified]`

- **6a. JWKS cache breaks permanently on key rotation.**
  `app/core/auth.py:19` `@lru_cache(maxsize=1)` is process-lifetime; a new `kid`
  raises `ValueError` at `:39`, and `verify_token` (`:58-61`) catches only
  `jwt.ExpiredSignatureError`/`InvalidTokenError` → unhandled 500 on every
  request until redeploy. Already bit once at the 2026-09-04 rotation.
  **Fix:** TTL cache, refetch once on unknown `kid`, catch `ValueError`/`URLError`
  → 401.
- **6b. Edge Functions unauthenticated.** All four deploy with
  `--no-verify-jwt` (`supabase/deploy.sh`) and no handler checks any shared
  secret — anyone with the URL can trigger pushes to real inverters and poison
  `agile_rates`, the table that drives real-money optimisation. **Fix:** a
  constant-time `CRON_SECRET` header check at the top of each `serve()`.
- **6c. HS256 fallback accepts Supabase infra keys** (`auth.py:41-56`,
  `verify_aud: False`, no `sub`/`iss`/`role` check). Anon/service_role keys
  verify as user tokens; `/tariff/prices` (`routes.py:190`) does no `sub` check.
  **Fix:** require non-empty `sub` (and ideally `iss`/`role`); or drop the
  fallback once legacy tokens expire.
- **6d. `/internal/optimise` internet-exposed** (`routes.py:483-528`) — static
  shared key, non-constant-time compare (`!=`), arbitrary `user_id`, skips the
  SOC-bound validation the public endpoint has. **Fix:** `secrets.compare_digest`,
  rotate, validate, scope the route.
- **6e. `routes.py:307`** blanket `except Exception` re-wraps the intentional
  `HTTPException(400, "NO_DATA: …")` raised at `:268` as
  "Optimisation failed: …", destroying the actionable message, and returns raw
  `str(e)` to the client. `optimise_and_push` gets this right (`:370-371`).
  Same pattern at `:438-444` double-wraps the formatted 502.
- **6f. Decrypted provider keys returned verbatim** in `GET /batteries/me`
  `[reported]`. Mask in responses; echo full values only on write.
- **6g. `database.py:5` no `pool_pre_ping`** `[verified]` — Render/Supabase
  pooler kills idle connections → sporadic 500s under low traffic.

## 7. Smaller, still real

- **`or` fallback overrides explicit 0** `[verified]` — `routes.py:349-353`:
  `req.min_soc_pct or battery.get(...)` turns a deliberate `0` into `20`.
  Compounded by `OptimiserForm.js:23` (`Number('') === 0`) sending `0` for a
  cleared capacity field. Fix: `x if x is not None else ...`.
- **Hardcoded BST** `[verified]` — `routes.py:206` and `data_provider.py`
  (`+01:00`) are wrong all winter; SQL uses DST-aware `Europe/London`. Use
  `zoneinfo.ZoneInfo("Europe/London")`.
- **Charts hardcode Europe/London** (`ScheduleCharts.js:22`) while the site
  timezone is user-selectable (`SetupWizard.js:175-178`, incl. Europe/Madrid).
  Matters for the Spain plan.
- **422 rendering** `[verified]` — `index.js:91-96` treats FastAPI's
  `detail` array as a string → `"[object Object]"`; `settings.js:140-141`
  renders the array as a React child → **page crash**. One shared
  `extractDetail()` fixes all six sites; also guard `response.json()` against
  cold-start HTML bodies (`SyntaxError: Unexpected token '<'`).
- **Agile 15-min→30-min aggregation misplaces `:15`** — `fetch-agile-prices/
  index.ts:73` normalises `:15 → :00` while `:30` stays, so the two quarters of
  a half-hour land in different buckets. Only bites if the feed is 15-min;
  verify granularity first.
- **Decrypt failure aborts the whole battery loop** (`optimise-and-push/
  index.ts:115` sits outside the per-battery try).
- **No auth guard on `/settings`** (`settings.js:22-31`) and the wizard shows
  an editable form to logged-out users.
- **`autoRanRef` never resets on sign-out** (`index.js:24`), so auto-optimise
  never runs again after switching accounts.
- **Dead code:** `forecast.py` (off the production path, incompatible column
  contract), `models/optimisation.py` (unreferenced), `solcast.py:18-24`
  (DB-first branch is a guaranteed `TypeError` hidden by a bare swallow),
  `tests/debug_opt.py` (calls a signature that no longer exists), `axios`
  (declared, unused), `checkedSessionRef`.

## Test gaps

- TS classifier / `foxess-schedule.ts` / `encryption.ts`: **zero tests**.
- `app/core/auth.py`: **zero tests** — the entire auth boundary of a live
  multi-tenant system. An unknown-`kid` test would have caught 6a.
- Tenant-isolation guards (`routes.py:75-76`, `:178-179`): no regression test.
- ~2 of 12 endpoints covered; `/optimise/push` (preview/push/failure) untested.
- Frontend: no tests, no test script.

## Rejected / false positives

- **Edge Function signature `\r\n` is NOT a bug.** `Md5.hashStr(\`${path}\\r\\n...\`)`
  was flagged as sending literal backslash-r instead of CRLF. Verified against
  the vendored reference `venv/.../foxesscloud/openapi.py:165`, which uses a
  **raw** f-string (`fr"{path}\r\n..."`) — so it sends the literal two-character
  sequence too. The TS matches the working path. Do not "fix" this.

## Not independently verified

Reviewer findings the orchestrator did not re-read: Solcast `PvEstimate * 0.5`
unit assumption (`solcast.py:33`), DST fall-back grouping collisions, whether
`_bucket_30` emits tz-aware timestamps (`data_provider.py:450`), and the exact
field set in `GET /batteries/me` (6f). Check these before acting.

## What's already correct

For balance — the LP core (units, pence→GBP conversion, kW·dt→kWh, balance
equation) is sound. Fernet encryption in both Python and TS is spec-correct
(fresh IV, HMAC-before-decrypt, PKCS7). SQL is parameterised throughout and the
dynamic `SET` allowlist is guarded. Token expiry is enforced and `alg: none` is
rejected. App-level tenant filters (`user_id`/`site_id`) are correct on every
query traced — note that RLS is bypassed by the owner-role connection, so those
filters are the *only* effective isolation.
