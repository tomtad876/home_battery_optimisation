import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.43.4";
import { Md5 } from "npm:ts-md5";
import { decryptProviderConfig } from "../shared/encryption.ts";
import { prepareScheduleGroups, OptimiserSlot, ClassifierConfig } from "../shared/classify-schedule.ts";
import { getDeviceScheduleInfo, getDeviceRemainMode, sendScheduleToInverter } from "../shared/foxess-schedule.ts";

const FOXESS_BASE_URL = "https://www.foxesscloud.com";

function signHeaders(path: string, apiKey: string, timestamp: number) {
  const signature = Md5.hashStr(`${path}\\r\\n${apiKey}\\r\\n${timestamp.toString()}`);
  return {
    "Content-Type": "application/json",
    signature,
    token: apiKey,
    timestamp: timestamp.toString(),
    lang: "en",
  };
}

async function fetchLiveSoc(foxessKey: string, deviceSn: string): Promise<number | null> {
  const path = "/op/v0/device/real/query";
  const ts = Date.now();
  const headers = signHeaders(path, foxessKey, ts);

  const resp = await fetch(`${FOXESS_BASE_URL}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify({ sn: deviceSn, variables: ["SoC"] }),
  });

  if (!resp.ok) return null;
  const data = await resp.json();
  for (const entry of data?.result?.[0]?.datas || []) {
    if (entry.variable === "SoC") return entry.value;
  }
  return null;
}

async function callBackendOptimise(
  userId: string,
  socPct: number,
  battery: {
    capacity_kwh: number;
    max_charge_kw: number;
    max_discharge_kw: number;
    min_soc_pct: number;
    max_soc_pct: number;
  }
): Promise<OptimiserSlot[] | null> {
  const backendUrl = Deno.env.get("BACKEND_URL");
  const internalKey = Deno.env.get("INTERNAL_API_KEY");
  if (!backendUrl || !internalKey) {
    console.error("optimise-and-push: BACKEND_URL or INTERNAL_API_KEY not set");
    return null;
  }

  const resp = await fetch(`${backendUrl}/internal/optimise`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Internal-Key": internalKey,
    },
    body: JSON.stringify({
      user_id: userId,
      battery_capacity_kwh: battery.capacity_kwh,
      initial_soc_pct: socPct,
      min_soc_pct: battery.min_soc_pct,
      max_soc_pct: battery.max_soc_pct,
      charge_power_kw: battery.max_charge_kw,
      discharge_power_kw: battery.max_discharge_kw,
    }),
  });

  if (!resp.ok) {
    const err = await resp.text();
    console.error(`optimise-and-push: backend error ${resp.status}: ${err}`);
    return null;
  }

  const data = await resp.json();
  return data?.schedule || null;
}

async function notify(summary: { success: boolean; processed: number; total: number; errors: string[] }) {
  // Sentry Crons heartbeat (the chosen provider). One terminal check-in per
  // run. monitor_config is re-sent so the monitor self-heals if ever deleted —
  // it was originally created by upsert from this same payload. A *missing*
  // check-in (cron disabled, function crashing before this point) is what makes
  // this a dead-man's switch, not just a failure alert (cf. 2026-09-13).
  const sentryCron = Deno.env.get("SENTRY_CRON_URL");
  if (sentryCron) {
    try {
      const resp = await fetch(sentryCron, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status: summary.success ? "ok" : "error",
          monitor_config: {
            schedule: { type: "crontab", value: "0,30 6-22 * * *" },
            timezone: "Europe/London",
            checkin_margin: 60,
            max_runtime: 15,
            failure_issue_threshold: 2,
            recovery_threshold: 1,
          },
        }),
      });
      if (!resp.ok) console.error(`optimise-and-push: sentry cron check-in returned ${resp.status}`);
    } catch (e) {
      console.error("optimise-and-push: sentry cron check-in failed", e);
    }
  }
  // Heartbeat / dead-man's switch. Ping on EVERY run so a *missing* ping (cron
  // disabled, function crashing before this point) also alerts — that is the
  // 2026-09-13 silent-failure mode a failure-only alert would miss.
  // healthchecks.io convention: success = the ping URL, failure = URL + /fail.
  const hc = Deno.env.get("HEALTHCHECK_PING_URL");
  if (hc) {
    try {
      const url = summary.success ? hc : `${hc.replace(/\/+$/, "")}/fail`;
      await fetch(url, {
        method: "POST",
        body: summary.success ? "ok" : (summary.errors.join("; ") || "failed"),
      });
    } catch (e) {
      console.error("optimise-and-push: heartbeat ping failed", e);
    }
  }
  // Optional generic webhook (Slack/Discord/ntfy). Failures only — not a noisy
  // per-run channel.
  const webhook = Deno.env.get("ALERT_WEBHOOK_URL");
  if (webhook && !summary.success) {
    try {
      await fetch(webhook, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: `Battery auto-push: ${summary.processed}/${summary.total} pushed. ${summary.errors.join("; ")}`,
        }),
      });
    } catch (e) {
      console.error("optimise-and-push: alert webhook failed", e);
    }
  }
}

serve(async (req: Request) => {
  console.log("optimise-and-push: invoked");

  // Shared-secret gate. The function deploys with --no-verify-jwt because
  // pg_cron cannot present a JWT the gateway will verify, so this header is the
  // real authentication (the function can push to real inverters). Fail closed:
  // no secret configured means refuse everything.
  const cronSecret = Deno.env.get("CRON_SECRET");
  if (!cronSecret || req.headers.get("x-cron-secret") !== cronSecret) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  try {
    const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    const encryptionKey = Deno.env.get("PROVIDER_CONFIG_ENCRYPTION_KEY");
    if (!supabaseKey) throw new Error("SUPABASE_SERVICE_ROLE_KEY not set");
    if (!encryptionKey) throw new Error("PROVIDER_CONFIG_ENCRYPTION_KEY not set");

    const client = createClient(Deno.env.get("SUPABASE_URL")!, supabaseKey);

    // Fetch all batteries with auto-push enabled
    const { data: batteries, error: battErr } = await client
      .from("batteries")
      .select("id, site_id, provider_config, capacity_kwh, max_charge_kw, max_discharge_kw, min_soc_pct, max_soc_pct")
      .eq("auto_push_enabled", true)
      .not("provider_config", "is", null);

    if (battErr) throw new Error(`Failed to fetch batteries: ${battErr.message}`);
    if (!batteries || batteries.length === 0) {
      await notify({ success: true, processed: 0, total: 0, errors: [] });
      return new Response(
        JSON.stringify({ success: true, message: "No batteries with auto-push enabled", processed: 0 }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    let processed = 0;
    const errors: string[] = [];
    const now = new Date();

    for (const battery of batteries) {
      const config = await decryptProviderConfig(battery.provider_config, encryptionKey);
      const foxessKey = config?.foxess_api_key;
      const deviceSn = config?.foxess_device_sn;

      if (!foxessKey || !deviceSn) {
        console.log(`optimise-and-push: skipping battery ${battery.id} — missing credentials`);
        continue;
      }

      // Get the site's user_id for the backend call
      const { data: site } = await client
        .from("sites")
        .select("user_id")
        .eq("id", battery.site_id)
        .single();

      if (!site?.user_id) {
        errors.push(`Battery ${battery.id}: no user_id on site`);
        continue;
      }

      try {
        // 1. Fetch live SOC
        const socPct = await fetchLiveSoc(foxessKey, deviceSn);
        if (socPct === null) {
          errors.push(`Battery ${battery.id}: could not fetch SOC`);
          continue;
        }

        // 2. Get device schedule info (maxGroupCount)
        const deviceInfo = await getDeviceScheduleInfo(foxessKey, deviceSn);

        // 3. Call backend optimiser
        const schedule = await callBackendOptimise(site.user_id, socPct, {
          capacity_kwh: battery.capacity_kwh,
          max_charge_kw: battery.max_charge_kw,
          max_discharge_kw: battery.max_discharge_kw,
          min_soc_pct: battery.min_soc_pct,
          max_soc_pct: battery.max_soc_pct,
        });

        if (!schedule || schedule.length === 0) {
          errors.push(`Battery ${battery.id}: optimiser returned no schedule`);
          continue;
        }

        // Refuse to push instructions built on backfilled prices. The optimiser
        // plans a 48h horizon whose tail is filled with a 7-day time-of-day
        // average and flagged is_synthetic; committing the inverter to a
        // "typical day" before the day-ahead prices publish is worse than
        // waiting for the next run (the 16:30 local Agile refresh). Published
        // prices are always a contiguous prefix, so dropping the synthetic tail
        // keeps the slots contiguous.
        const realSchedule = (schedule as OptimiserSlot[]).filter((s) => !s.is_synthetic);
        if (realSchedule.length < 2) {
          const msg = `Battery ${battery.id}: no published-price slots in the horizon — skipping synthetic plan`;
          errors.push(msg);
          await client.from("schedules").insert({
            status: "failed",
            pushed_at: now.toISOString(),
            trigger_source: "cron",
            soc_at_push: socPct,
            error_message: msg,
            foxess_groups: [],
          });
          continue;
        }

        // 4. Classify into FoxESS groups. maxGroupCount includes the remain-mode
        // group, and prepareScheduleGroups guarantees the pushed list fits it
        // (classify → drop remain → split midnight → merge to maxGroups-1 →
        // append remain) — the same pipeline the manual Python path uses.
        const maxGroups = deviceInfo.maxGroupCount || 8;
        const classifierConfig: ClassifierConfig = {
          threshold: 0.05,
          capacityKwh: battery.capacity_kwh,
          minSocPct: battery.min_soc_pct,
          maxSocPct: battery.max_soc_pct,
          ratedPowerW: battery.max_charge_kw * 1000,
          maxGroups,
          supportedModes: ["SelfUse", "ForceCharge", "ForceDischarge", "Feedin"],
        };

        // Fall back to SelfUse (FoxESS default) if the device can't report its
        // remain mode — e.g. right after a push that wiped the remain-mode group.
        const remainMode = (await getDeviceRemainMode(foxessKey, deviceSn)) || "SelfUse";
        const finalGroups = prepareScheduleGroups(realSchedule, classifierConfig, now, remainMode);

        // 5. Push to inverter. Capture failures instead of throwing past the
        // audit write, so every run is logged and the response status reflects it.
        let pushed = false;
        let providerResponse: unknown = null;
        let pushError: string | null = null;
        try {
          const result = await sendScheduleToInverter(foxessKey, deviceSn, finalGroups as any[]);
          pushed = true;
          providerResponse = result.providerResponse;
        } catch (e) {
          pushError = e instanceof Error ? e.message : String(e);
          errors.push(`Battery ${battery.id}: push failed: ${pushError}`);
        }

        // 6. Log to schedules table — audit the groups actually sent, not the
        // pre-merge/pre-split classifier output.
        const { data: lastRun } = await client
          .from("optimisation_runs")
          .select("id")
          .eq("site_id", battery.site_id)
          .order("created_at", { ascending: false })
          .limit(1)
          .single();

        await client.from("schedules").insert({
          optimisation_run_id: lastRun?.id || null,
          status: pushed ? "sent" : "failed",
          pushed_at: now.toISOString(),
          foxess_groups: finalGroups,
          trigger_source: "cron",
          soc_at_push: socPct,
          provider_response: providerResponse,
          error_message: pushError,
        });

        if (pushed) {
          processed++;
          console.log(`optimise-and-push: battery ${battery.id} — pushed ${finalGroups.length} groups, SOC ${socPct}%`);
        }
      } catch (e) {
        errors.push(`Battery ${battery.id}: ${e instanceof Error ? e.message : String(e)}`);
      }
    }

    await notify({ success: errors.length === 0, processed, total: batteries.length, errors });

    return new Response(
      JSON.stringify({
        success: errors.length === 0,
        processed,
        total: batteries.length,
        errors: errors.length > 0 ? errors : undefined,
      }),
      { status: errors.length === 0 ? 200 : 500, headers: { "Content-Type": "application/json" } }
    );
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    await notify({ success: false, processed: 0, total: 0, errors: [msg] });
    return new Response(JSON.stringify({ error: msg }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});
