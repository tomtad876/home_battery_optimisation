import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.43.4";
import { Md5 } from "npm:ts-md5";
import { decryptProviderConfig } from "../shared/encryption.ts";
import { classifySchedule, OptimiserSlot, ClassifierConfig } from "../shared/classify-schedule.ts";
import { getDeviceScheduleInfo, getDeviceRemainMode, splitGroupsAtMidnight, sendScheduleToInverter } from "../shared/foxess-schedule.ts";

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

serve(async (req: Request) => {
  console.log("optimise-and-push: invoked");
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

        // 4. Classify into FoxESS groups
        const classifierConfig: ClassifierConfig = {
          threshold: 0.05,
          capacityKwh: battery.capacity_kwh,
          minSocPct: battery.min_soc_pct,
          maxSocPct: battery.max_soc_pct,
          ratedPowerW: battery.max_charge_kw * 1000,
          maxGroups: deviceInfo.maxGroupCount,
          supportedModes: ["SelfUse", "ForceCharge", "ForceDischarge", "Feedin"],
        };

        const groups = classifySchedule(schedule, classifierConfig, now);

        // Drop groups matching the device's remain (default) mode — those
        // instructions are redundant since the inverter already falls back to
        // that mode in unscheduled gaps.
        const remainMode = await getDeviceRemainMode(foxessKey, deviceSn);
        let finalGroups = remainMode
          ? groups.filter((g: any) => g.workMode !== remainMode)
          : groups;

        // Split any group that spans midnight (FoxESS rejects cross-midnight periods)
        finalGroups = splitGroupsAtMidnight(finalGroups);

        if (finalGroups.length === 0) {
          errors.push(`Battery ${battery.id}: no groups after classification`);
          continue;
        }

        // 5. Push to inverter
        const result = await sendScheduleToInverter(foxessKey, deviceSn, finalGroups as any[]);

        // 6. Log to schedules table
        const { data: lastRun } = await client
          .from("optimisation_runs")
          .select("id")
          .eq("site_id", battery.site_id)
          .order("created_at", { ascending: false })
          .limit(1)
          .single();

        await client.from("schedules").insert({
          optimisation_run_id: lastRun?.id || null,
          status: result.pushed ? "sent" : "failed",
          pushed_at: now.toISOString(),
          foxess_groups: groups,
          trigger_source: "cron",
          soc_at_push: socPct,
          provider_response: result.providerResponse,
          error_message: result.pushed ? null : "Push failed",
        });

        processed++;
        console.log(`optimise-and-push: battery ${battery.id} — pushed ${groups.length} groups, SOC ${socPct}%`);
      } catch (e) {
        errors.push(`Battery ${battery.id}: ${e.message}`);
      }
    }

    return new Response(
      JSON.stringify({
        success: errors.length === 0,
        processed,
        total: batteries.length,
        errors: errors.length > 0 ? errors : undefined,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});
