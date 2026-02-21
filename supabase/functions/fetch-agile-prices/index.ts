import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.43.4";

serve(async (req: Request) => {
  console.log("fetch-agile-prices: invoked");
  try {
    // SUPABASE_URL is auto-provided by Supabase; only set SERVICE_ROLE_KEY as a secret
    const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    const foxessKey = Deno.env.get("FOXESS_API_KEY");

    console.log("env: SERVICE_ROLE_KEY present=", !!supabaseKey, "FOXESS_API_KEY present=", !!foxessKey);
    if (!supabaseKey) throw new Error("SUPABASE_SERVICE_ROLE_KEY not set");
    if (!foxessKey) throw new Error("FOXESS_API_KEY not set");

    const client = createClient(Deno.env.get("SUPABASE_URL")!, supabaseKey);

    // Check last successful run
      // Check if agile_rates already has rows for today
      const today = new Date();
      today.setUTCHours(0, 0, 0, 0);
      const tomorrow = new Date(today);
      tomorrow.setUTCDate(today.getUTCDate() + 1);

      const { data: existingRates, error: ratesError } = await client
        .from("agile_rates")
        .select("period_end")
        .gte("period_end", today.toISOString())
        .lt("period_end", tomorrow.toISOString());

      if (existingRates && existingRates.length > 0) {
        return new Response(
          JSON.stringify({
            skipped: true,
            message: "Agile rates already exist for today",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }

    // Call FoxESS API to get Agile prices
    // Note: this requires the foxesscloud SDK or direct HTTP to FoxESS
    // For now, we assume you have a helper; in production you'd fetch directly via HTTP
    const foxessUrl = "https://www.foxesscloud.com/c/v0/device/agile";
        // Fetch Agile rates JSON (agilerates.uk) for the chosen region
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

        let intervals = [];
        for (const r of rates) {
          // deliveryEnd is ISO8601 UTC
          const periodEnd = r.deliveryEnd || r.delivery_end || r.deliveryEndUTC || null;
          if (!periodEnd) continue;
          const importPrice = r?.agileRate?.result?.rate ?? null;
          const exportPrice = r?.agileOutgoingRate?.result?.rate ?? null;

            // Only insert if both prices are not null
            if (importPrice !== null && exportPrice !== null) {
              intervals.push({
                id: crypto.randomUUID(),
                period_end: periodEnd,
                import_price: importPrice,
                export_price: exportPrice,
              });
            }
        }

          // Remove interval data logging, but log upsert step
          console.log("fetch-agile-prices: upserting intervals into agile_rates...");

        if (!intervals || intervals.length === 0) {
          console.log("fetch-agile-prices: parsed 0 intervals");
          return new Response(
            JSON.stringify({ error: "No valid price intervals parsed" }),
            { status: 400, headers: { "Content-Type": "application/json" } }
          );
        }

        // Upsert
        const upsertResp = await client.from("agile_rates").upsert(intervals, {
          onConflict: "period_end",
        });
        console.log("fetch-agile-prices: upsert response", upsertResp.error ? upsertResp.error : "ok");

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
