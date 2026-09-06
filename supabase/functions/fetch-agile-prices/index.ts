import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.43.4";

serve(async (req: Request) => {
  console.log("fetch-agile-prices: invoked");
  try {
    const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");

    if (!supabaseKey) throw new Error("SUPABASE_SERVICE_ROLE_KEY not set");

    const client = createClient(Deno.env.get("SUPABASE_URL")!, supabaseKey);

    const region = Deno.env.get("AGILE_REGION_CODE") || "E";
    const agileUrl = `https://agilerates.uk/api/agile_rates_region_${region}.json`;

    console.log("fetch-agile-prices: fetching from", agileUrl);

    const resp = await fetch(agileUrl);
    if (!resp.ok) {
      console.log("fetch-agile-prices: fetch failed", resp.status);
      return new Response(
        JSON.stringify({ error: `AgileRates API error: ${resp.status}` }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    const data = await resp.json();
    const rates = Array.isArray(data?.rates) ? data.rates : null;

    if (!rates || rates.length === 0) {
      return new Response(
        JSON.stringify({ error: "No rates found in response" }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    // Parse all 15-min intervals
    const parsed: { periodEnd: string; importPrice: number; exportPrice: number }[] = [];

    for (const r of rates) {
      const periodEnd =
        r.deliveryEnd || r.delivery_end || r.deliveryEndUTC || null;
      if (!periodEnd) continue;

      const importPrice = r?.agileRate?.result?.rate ?? null;
      const exportPrice = r?.agileOutgoingRate?.result?.rate ?? null;

      if (importPrice !== null && exportPrice !== null) {
        parsed.push({ periodEnd, importPrice, exportPrice });
      }
    }

    console.log(`fetch-agile-prices: parsed ${parsed.length} 15-min intervals`);

    if (parsed.length === 0) {
      return new Response(
        JSON.stringify({ error: "No valid price intervals parsed" }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    // Aggregate 15-min → 30-min by averaging each pair
    // 15-min slots at :00 and :15 → 30-min slot at :00
    // 15-min slots at :30 and :45 → 30-min slot at :30
    const bySlot = new Map<string, { importSum: number; exportSum: number; count: number }>();

    for (const p of parsed) {
      // Normalize to 30-min boundary
      const d = new Date(p.periodEnd);
      const minute = d.getUTCMinutes();
      // Round down to :00 or :30
      const normalized = new Date(d);
      if (minute === 15 || minute === 45) {
        normalized.setUTCMinutes(minute - 15, 0, 0);
      }
      const key = normalized.toISOString();

      const existing = bySlot.get(key) || { importSum: 0, exportSum: 0, count: 0 };
      existing.importSum += p.importPrice;
      existing.exportSum += p.exportPrice;
      existing.count += 1;
      bySlot.set(key, existing);
    }

    // Build upsert rows — average the 15-min rates for each 30-min slot
    const intervals: { id: string; period_end: string; import_price: number; export_price: number }[] = [];

    for (const [periodEnd, agg] of bySlot) {
      intervals.push({
        id: crypto.randomUUID(),
        period_end: periodEnd,
        import_price: Math.round((agg.importSum / agg.count) * 100) / 100,
        export_price: Math.round((agg.exportSum / agg.count) * 100) / 100,
      });
    }

    console.log(`fetch-agile-prices: aggregated to ${intervals.length} 30-min slots`);

    // Upsert in batches of 500 to avoid payload limits
    const BATCH = 500;
    let totalUpserted = 0;
    for (let i = 0; i < intervals.length; i += BATCH) {
      const batch = intervals.slice(i, i + BATCH);
      const upsertResp = await client.from("agile_rates").upsert(batch, {
        onConflict: "period_end",
      });
      if (upsertResp.error) {
        console.log("fetch-agile-prices: upsert error", upsertResp.error);
        throw new Error(`Upsert failed: ${upsertResp.error.message}`);
      }
      totalUpserted += batch.length;
    }

    console.log(`fetch-agile-prices: upserted ${totalUpserted} rows`);

    return new Response(
      JSON.stringify({ success: true, intervals: totalUpserted }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  } catch (error: any) {
    console.error("fetch-agile-prices: error", error.message);
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});
