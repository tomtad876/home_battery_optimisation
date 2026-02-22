import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.43.4";

serve(async (req: Request) => {
  console.log("fetch-agile-prices: invoked");
  try {
    const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    const foxessKey = Deno.env.get("FOXESS_API_KEY");

    console.log(
      "env: SERVICE_ROLE_KEY present=",
      !!supabaseKey,
      "FOXESS_API_KEY present=",
      !!foxessKey
    );

    if (!supabaseKey) throw new Error("SUPABASE_SERVICE_ROLE_KEY not set");
    if (!foxessKey) throw new Error("FOXESS_API_KEY not set");

    const client = createClient(Deno.env.get("SUPABASE_URL")!, supabaseKey);

    // Always fetch and overwrite — no "already exists" check

    const region = Deno.env.get("AGILE_REGION_CODE") || "E";
    const agileUrl = `https://agilerates.uk/api/agile_rates_region_${region}.json`;

    console.log("fetch-agile-prices: fetching agile rates from", agileUrl);

    const resp = await fetch(agileUrl);
    if (!resp.ok) {
      console.log("fetch-agile-prices: agileRates fetch failed", resp.status);
      return new Response(
        JSON.stringify({ error: `AgileRates API error: ${resp.status}` }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    const data = await resp.json();
    const rates = Array.isArray(data?.rates) ? data.rates : null;

    if (!rates || rates.length === 0) {
      console.log("fetch-agile-prices: no rates in agileRates response");
      return new Response(
        JSON.stringify({ error: "No rates found in agileRates response" }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    const intervals = [];

    for (const r of rates) {
      const periodEnd =
        r.deliveryEnd || r.delivery_end || r.deliveryEndUTC || null;

      if (!periodEnd) continue;

      const importPrice = r?.agileRate?.result?.rate ?? null;
      const exportPrice = r?.agileOutgoingRate?.result?.rate ?? null;

      if (importPrice !== null && exportPrice !== null) {
        intervals.push({
          id: crypto.randomUUID(),
          period_end: periodEnd,
          import_price: importPrice,
          export_price: exportPrice,
        });
      }
    }

    console.log(
      "fetch-agile-prices: upserting intervals into agile_rates..."
    );

    if (intervals.length === 0) {
      console.log("fetch-agile-prices: parsed 0 intervals");
      return new Response(
        JSON.stringify({ error: "No valid price intervals parsed" }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    const upsertResp = await client.from("agile_rates").upsert(intervals, {
      onConflict: "period_end",
    });

    console.log(
      "fetch-agile-prices: upsert response",
      upsertResp.error ? upsertResp.error : "ok"
    );

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