import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.43.4";
import { Md5 } from "npm:ts-md5";

serve(async (req: Request) => {
  console.log("fetch-demand: invoked");
  try {
    const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    const foxessKey = Deno.env.get("FOXESS_API_KEY");

    console.log("env: SERVICE_ROLE_KEY present=", !!supabaseKey, "FOXESS_API_KEY present=", !!foxessKey);
    if (!supabaseKey) throw new Error("SUPABASE_SERVICE_ROLE_KEY not set");

    const client = createClient(Deno.env.get("SUPABASE_URL")!, supabaseKey);


    // Fetch demand history from FoxESS
    const deviceSn = Deno.env.get("FOXESS_DEVICE_SN");
    if (!foxessKey) throw new Error("FOXESS_API_KEY not set");
    if (!deviceSn) throw new Error("FOXESS_DEVICE_SN not set");

    // Fetch demand history for the past week
    const now = new Date();
    let intervals = [];
    for (let i = 1; i >= 0; i--) {
      const day = new Date(now.getTime() - i * 24 * 60 * 60 * 1000);
      const dayStr = day.toISOString().slice(0, 10);
      // FoxESS API header/signature
      const path = "/op/v0/device/history/query";
      const timestamp = Date.now();
      const signature = Md5.hashStr(`${path}\\r\\n${foxessKey}\\r\\n${timestamp.toString()}`);
      const headers = {
        "Content-Type": "application/json",
        signature,
        token: foxessKey,
        timestamp: timestamp.toString(),
        lang: "en"
      };
      // FoxESS API expects begin/end as milliseconds
      const beginDate = new Date(dayStr + "T00:00:00Z");
      const endDate = new Date(dayStr + "T23:59:59Z");
      const body = {
        sn: deviceSn,
        variables: ['generationPower', 'feedinPower','loadsPower','gridConsumptionPower','batChargePower', 'batDischargePower', 'pvPower', 'meterPower2'],
        begin: beginDate.getTime(),
        end: endDate.getTime()
      };
      const foxessResp = await fetch("https://www.foxesscloud.com" + path, {
        method: "POST",
        headers,
        body: JSON.stringify(body)
      });
      if (!foxessResp.ok) {
        console.log(`fetch-demand: FoxESS API error for ${dayStr}:`, foxessResp.status);
        continue;
      }
      const foxessData = await foxessResp.json();
      const result = foxessData?.result?.[0]?.datas || [];
      for (const entry of result) {
        // Each entry: { variable, unit, name, data: [{ value, time }] }
        const variable = entry?.variable;
        const unit = entry?.unit;
        const name = entry?.name;
        const dataArr = entry?.data || [];
        for (const d of dataArr) {
          const value = d?.value;
          const time = d?.time;
          if (value == null || !time) continue;
          intervals.push({
            id: crypto.randomUUID(),
            period_end: time,
            variable,
            unit,
            name,
            value,
            time
          });
        }
      }
    }

    if (!intervals || intervals.length === 0) {
      return new Response(
        JSON.stringify({ error: "No valid demand intervals from FoxESS" }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    // Upsert
    console.log("fetch-demand: upserting intervals into historic_energy_data...");
    const upsertResp = await client.from("historic_energy_data").upsert(intervals, {
    onConflict: ["period_end", "variable"], // match the unique constraint
    });

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
