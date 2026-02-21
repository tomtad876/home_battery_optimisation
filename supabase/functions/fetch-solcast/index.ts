import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.43.4";

serve(async (req: Request) => {
  console.log("fetch-solcast: invoked");
  try {
    const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    const solcastKey = Deno.env.get("SOLCAST_API_KEY");
    const pvSystemId = Deno.env.get("SOLCAST_PV_SYSTEM_ID");

    console.log("env: SERVICE_ROLE_KEY present=", !!supabaseKey, "SOLCAST_API_KEY=", !!solcastKey, "PV_ID=", !!pvSystemId);
    if (!supabaseKey) throw new Error("SUPABASE_SERVICE_ROLE_KEY not set");
    if (!solcastKey) throw new Error("SOLCAST_API_KEY not set");
    if (!pvSystemId) throw new Error("SOLCAST_PV_SYSTEM_ID not set");

    const client = createClient(Deno.env.get("SUPABASE_URL")!, supabaseKey);


    // Fetch from Solcast
    const url = `https://api.solcast.com.au/rooftop_sites/${pvSystemId}/forecasts?format=csv`;
    const resp = await fetch(url, {
      headers: {
        Authorization: `Basic ${btoa(solcastKey + ":")}`,
      },
    });

    if (!resp.ok) {
      return new Response(
        JSON.stringify({ error: `Solcast API error: ${resp.status}` }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    const csv = await resp.text();
    const lines = csv.trim().split("\n");
    const header = lines[0].split(",");
    const periodEndIdx = header.indexOf("PeriodEnd");
    const pvEstimateIdx = header.indexOf("PvEstimate");

    if (periodEndIdx === -1 || pvEstimateIdx === -1) {
      return new Response(
        JSON.stringify({ error: "Missing PeriodEnd or PvEstimate in CSV" }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    // Parse and insert into solcast_forecast
    let intervals = [];
    for (let i = 1; i < lines.length; i++) {
      const parts = lines[i].split(",");
      const periodEnd = parts[periodEndIdx]?.trim();
      const pvEstimate = parseFloat(parts[pvEstimateIdx]?.trim() || "0");
      if (!periodEnd || isNaN(pvEstimate)) continue;
      // Convert power (kW) to energy over 30 min (kWh)
      const energyKwh = pvEstimate * 0.5;
      intervals.push({
        id: crypto.randomUUID(),
        period_end: periodEnd,
        solar_kwh: energyKwh,
      });
    }

    if (!intervals || intervals.length === 0) {
      return new Response(
        JSON.stringify({ error: "No valid intervals in Solcast response" }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    // Batch insert (upsert by period_end)
    console.log("fetch-solcast: upserting intervals into solcast_forecast...");
    const upsertResp = await client.from("solcast_forecast").upsert(intervals, {
      onConflict: "period_end",
    });
    console.log("fetch-solcast: upsert response", upsertResp.error ? upsertResp.error : "ok");

    return new Response(
      JSON.stringify({ success: true, intervals: intervals.length }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});
