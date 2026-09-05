import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.43.4";
import { decryptProviderConfig } from "../shared/encryption.ts";

serve(async (req: Request) => {
  console.log("fetch-solcast: invoked");
  try {
    const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    const encryptionKey = Deno.env.get("PROVIDER_CONFIG_ENCRYPTION_KEY");
    if (!supabaseKey) throw new Error("SUPABASE_SERVICE_ROLE_KEY not set");
    if (!encryptionKey) throw new Error("PROVIDER_CONFIG_ENCRYPTION_KEY not set");

    const client = createClient(Deno.env.get("SUPABASE_URL")!, supabaseKey);

    // Fetch all batteries with Solcast credentials
    const { data: batteries, error: battErr } = await client
      .from("batteries")
      .select("id, site_id, provider_config")
      .not("provider_config", "is", null);

    if (battErr) throw new Error(`Failed to fetch batteries: ${battErr.message}`);
    if (!batteries || batteries.length === 0) {
      return new Response(
        JSON.stringify({ success: true, message: "No batteries with credentials configured", intervals: 0 }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    let totalIntervals = 0;
    const errors: string[] = [];

    for (const battery of batteries) {
      const config = decryptProviderConfig(battery.provider_config, encryptionKey);
      const solcastKey = config?.solcast_api_key;
      const pvSystemId = config?.solcast_system_id;

      if (!solcastKey || !pvSystemId) {
        console.log(`fetch-solcast: skipping battery ${battery.id} — missing solcast_api_key or solcast_system_id`);
        continue;
      }

      try {
        const url = `https://api.solcast.com.au/rooftop_sites/${pvSystemId}/forecasts?format=csv`;
        const resp = await fetch(url, {
          headers: {
            Authorization: `Basic ${btoa(solcastKey + ":")}`,
          },
        });

        if (!resp.ok) {
          const msg = `Solcast API error ${resp.status} for site ${battery.site_id}`;
          console.log(`fetch-solcast: ${msg}`);
          errors.push(msg);
          continue;
        }

        const csv = await resp.text();
        const lines = csv.trim().split("\n");
        const header = lines[0].split(",");
        const periodEndIdx = header.indexOf("PeriodEnd");
        const pvEstimateIdx = header.indexOf("PvEstimate");

        if (periodEndIdx === -1 || pvEstimateIdx === -1) {
          errors.push(`Missing PeriodEnd or PvEstimate for site ${battery.site_id}`);
          continue;
        }

        const intervals = [];
        for (let i = 1; i < lines.length; i++) {
          const parts = lines[i].split(",");
          const periodEnd = parts[periodEndIdx]?.trim();
          const pvEstimate = parseFloat(parts[pvEstimateIdx]?.trim() || "0");
          if (!periodEnd || isNaN(pvEstimate)) continue;
          const energyKwh = pvEstimate * 0.5;
          intervals.push({
            id: crypto.randomUUID(),
            period_end: periodEnd,
            solar_kwh: energyKwh,
            site_id: battery.site_id,
          });
        }

        if (intervals.length === 0) continue;

        const upsertResp = await client.from("solcast_forecast").upsert(intervals, {
          onConflict: "period_end",
        });

        if (upsertResp.error) {
          errors.push(`Upsert error for site ${battery.site_id}: ${upsertResp.error.message}`);
        } else {
          totalIntervals += intervals.length;
          console.log(`fetch-solcast: upserted ${intervals.length} intervals for site ${battery.site_id}`);
        }
      } catch (e) {
        errors.push(`Error fetching for site ${battery.site_id}: ${e.message}`);
      }
    }

    return new Response(
      JSON.stringify({
        success: errors.length === 0,
        intervals: totalIntervals,
        sites_processed: batteries.length,
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
