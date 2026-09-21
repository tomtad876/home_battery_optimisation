import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.43.4";
import { Md5 } from "npm:ts-md5";
import { decryptProviderConfig } from "../shared/encryption.ts";

// Power variables pulled from FoxESS.
const POWER_VARIABLES = [
  "generationPower",
  "feedinPower",
  "loadsPower",
  "gridConsumptionPower",
  "batChargePower",
  "batDischargePower",
  "pvPower",
  "meterPower2",
];

const HISTORY_PATH = "/op/v0/device/history/query";
const ROLLING_HOURS = 4;          // default cron window
const MAX_BACKFILL_DAYS = 31;     // safety cap on a single backfill request
const PAD_MS = 2 * 60 * 60 * 1000; // pad day windows ±2h to cover the local boundary

interface Window { begin: number; end: number }

interface FoxessCredentials {
  foxess_api_key?: string;
  foxess_device_sn?: string;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Constant-time string compare (avoids leaking the secret via timing). */
function secretMatches(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function foxessHeaders(apiKey: string): Record<string, string> {
  const timestamp = Date.now();
  // NB: the literal backslash-r/backslash-n below (not real CRLF) matches the
  // vendored foxesscloud signature scheme — do not "fix" it.
  const signature = Md5.hashStr(`${HISTORY_PATH}\\r\\n${apiKey}\\r\\n${timestamp.toString()}`);
  return {
    "Content-Type": "application/json",
    signature,
    token: apiKey,
    timestamp: timestamp.toString(),
    lang: "en",
  };
}

/** One FoxESS history call. Returns DB-ready rows (site_id added by caller). */
async function fetchWindow(
  credentials: FoxessCredentials,
  begin: number,
  end: number,
): Promise<Record<string, unknown>[]> {
  const resp = await fetch("https://www.foxesscloud.com" + HISTORY_PATH, {
    method: "POST",
    headers: foxessHeaders(credentials.foxess_api_key!),
    body: JSON.stringify({
      sn: credentials.foxess_device_sn,
      variables: POWER_VARIABLES,
      begin,
      end,
    }),
  });
  if (!resp.ok) throw new Error(`FoxESS HTTP ${resp.status}`);

  const data = await resp.json();
  const intervals: Record<string, unknown>[] = [];
  for (const entry of data?.result?.[0]?.datas || []) {
    for (const d of entry?.data || []) {
      if (d?.value == null || !d?.time) continue;
      intervals.push({
        id: crypto.randomUUID(),
        period_end: d.time,
        variable: entry.variable,
        unit: entry.unit,
        name: entry.name,
        value: d.value,
        time: d.time,
      });
    }
  }
  return intervals;
}

/**
 * Resolve the requested windows, or null for the default rolling 4h.
 *
 * Accepted (query string or JSON body): `begin`+`end` (epoch ms), or `day`
 * (YYYY-MM-DD), or `from`+`to` (YYYY-MM-DD). Dates are treated as UTC and
 * padded ±2h so the local (Europe/London) day boundary is covered — over-
 * fetching is harmless because the upsert is idempotent.
 */
function resolveWindows(body: Record<string, unknown> | null, url: URL): Window[] | null {
  const param = (key: string) =>
    url.searchParams.get(key) ?? (body?.[key] != null ? String(body[key]) : null);

  const begin = param("begin");
  const end = param("end");
  if (begin && end) {
    const b = Number(begin);
    const e = Number(end);
    if (!Number.isFinite(b) || !Number.isFinite(e) || e <= b) {
      throw new Error("Invalid begin/end (expect epoch ms, end > begin)");
    }
    const spanDays = (e - b) / 86400000;
    if (spanDays > MAX_BACKFILL_DAYS + 1) {
      throw new Error(`begin/end spans ${Math.round(spanDays)} days; max ${MAX_BACKFILL_DAYS}`);
    }
    return [{ begin: b, end: e }];
  }

  const day = param("day");
  const days = param("days");
  const from = param("from");
  const to = param("to");
  if (!day && !days && !from && !to) return null; // default rolling mode

  const dayStarts: number[] = [];
  if (day) dayStarts.push(Date.parse(`${day}T00:00:00Z`));
  if (from && to) {
    for (let t = Date.parse(`${from}T00:00:00Z`); t <= Date.parse(`${to}T00:00:00Z`); t += 86400000) {
      dayStarts.push(t);
    }
  }
  if (days) {
    const n = Number(days);
    const todayUtc = Date.parse(`${new Date().toISOString().slice(0, 10)}T00:00:00Z`);
    for (let i = 0; i < n; i++) dayStarts.push(todayUtc - i * 86400000);
  }

  const unique = [...new Set(dayStarts.filter((t) => Number.isFinite(t)))];
  if (unique.length === 0) throw new Error("Could not parse the requested day(s)");
  if (unique.length > MAX_BACKFILL_DAYS) {
    throw new Error(`Too many days requested (${unique.length}); max ${MAX_BACKFILL_DAYS}`);
  }
  return unique.sort((a, b) => a - b).map((t) => ({ begin: t - PAD_MS, end: t + 86400000 + PAD_MS }));
}

serve(async (req: Request) => {
  console.log("fetch-demand: invoked");
  try {
    const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    const encryptionKey = Deno.env.get("PROVIDER_CONFIG_ENCRYPTION_KEY");
    if (!supabaseKey) throw new Error("SUPABASE_SERVICE_ROLE_KEY not set");
    if (!encryptionKey) throw new Error("PROVIDER_CONFIG_ENCRYPTION_KEY not set");

    const url = new URL(req.url);
    let body: Record<string, unknown> | null = null;
    if (req.method !== "GET" && req.method !== "HEAD") {
      try {
        body = await req.json();
      } catch {
        body = null; // cron invokes with no body — the normal case
      }
    }

    let windows: Window[] | null;
    try {
      windows = resolveWindows(body, url);
    } catch (e) {
      return json({ error: (e as Error).message }, 400);
    }

    // Backfill can request large historical windows, so it is gated behind a
    // shared secret and fails closed if BACKFILL_SECRET is unset. The default
    // 4h cron path needs no secret (unchanged behaviour).
    if (windows) {
      const secret = Deno.env.get("BACKFILL_SECRET");
      const provided = req.headers.get("x-backfill-secret") || "";
      if (!secret || !secretMatches(provided, secret)) {
        return json(
          { error: "Backfill requires a valid x-backfill-secret header (set BACKFILL_SECRET)" },
          403,
        );
      }
    } else {
      const now = Date.now();
      windows = [{ begin: now - ROLLING_HOURS * 60 * 60 * 1000, end: now }];
    }

    const client = createClient(Deno.env.get("SUPABASE_URL")!, supabaseKey);

    // Fetch all batteries with FoxESS credentials
    const { data: batteries, error: battErr } = await client
      .from("batteries")
      .select("id, site_id, provider_config")
      .not("provider_config", "is", null);

    if (battErr) throw new Error(`Failed to fetch batteries: ${battErr.message}`);
    if (!batteries || batteries.length === 0) {
      return json({ success: true, message: "No batteries with credentials configured", intervals: 0 });
    }

    let totalIntervals = 0;
    const errors: string[] = [];

    for (const battery of batteries) {
      const config = await decryptProviderConfig(battery.provider_config, encryptionKey);
      const credentials: FoxessCredentials = {
        foxess_api_key: config?.foxess_api_key,
        foxess_device_sn: config?.foxess_device_sn,
      };

      if (!credentials.foxess_api_key || !credentials.foxess_device_sn) {
        console.log(`fetch-demand: skipping battery ${battery.id} — missing foxess_api_key or foxess_device_sn`);
        continue;
      }

      try {
        const intervals: Record<string, unknown>[] = [];
        for (const w of windows) {
          const rows = await fetchWindow(credentials, w.begin, w.end);
          for (const row of rows) row.site_id = battery.site_id;
          intervals.push(...rows);
        }

        if (intervals.length === 0) {
          console.log(`fetch-demand: no intervals for site ${battery.site_id}`);
          continue;
        }

        // onConflict is a comma-separated string (the old array only worked
        // because JS coerced it to "period_end,variable"). Must match the
        // UNIQUE(site_id, period_end, variable) constraint.
        const upsertResp = await client.from("historic_energy_data").upsert(intervals, {
          onConflict: "site_id,period_end,variable",
        });

        if (upsertResp.error) {
          errors.push(`Upsert error for site ${battery.site_id}: ${upsertResp.error.message}`);
        } else {
          totalIntervals += intervals.length;
          console.log(`fetch-demand: upserted ${intervals.length} intervals for site ${battery.site_id}`);
        }
      } catch (e) {
        errors.push(`Error fetching for site ${battery.site_id}: ${(e as Error).message}`);
      }
    }

    return json({
      success: errors.length === 0,
      mode: windows.length === 1 && windows[0].end - windows[0].begin <= ROLLING_HOURS * 60 * 60 * 1000
        ? "rolling"
        : "backfill",
      windows: windows.length,
      intervals: totalIntervals,
      sites_processed: batteries.length,
      errors: errors.length > 0 ? errors : undefined,
    });
  } catch (error) {
    return json({ error: (error as Error).message }, 500);
  }
});
