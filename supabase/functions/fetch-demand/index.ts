import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.43.4";
import { Md5 } from "npm:ts-md5";
import { decryptProviderConfig } from "../shared/encryption.ts";

serve(async (req: Request) => {
  console.log("fetch-demand: invoked");
  try {
    const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    const encryptionKey = Deno.env.get("PROVIDER_CONFIG_ENCRYPTION_KEY");
    if (!supabaseKey) throw new Error("SUPABASE_SERVICE_ROLE_KEY not set");
    if (!encryptionKey) throw new Error("PROVIDER_CONFIG_ENCRYPTION_KEY not set");

    const client = createClient(Deno.env.get("SUPABASE_URL")!, supabaseKey);

    // Fetch all batteries with FoxESS credentials
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
      const config = await decryptProviderConfig(battery.provider_config, encryptionKey);
      const foxessKey = config?.foxess_api_key;
      const deviceSn = config?.foxess_device_sn;

      if (!foxessKey || !deviceSn) {
        console.log(`fetch-demand: skipping battery ${battery.id} — missing foxess_api_key or foxess_device_sn`);
        continue;
      }

      try {
        const now = new Date();
        const intervals = [];

        // Fetch last 7 days of demand history
        for (let i = 6; i >= 0; i--) {
          const day = new Date(now.getTime() - i * 24 * 60 * 60 * 1000);
          const dayStr = day.toISOString().slice(0, 10);

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

          const beginDate = new Date(dayStr + "T00:00:00Z");
          const endDate = new Date(dayStr + "T23:59:59Z");
          const body = {
            sn: deviceSn,
            variables: ['generationPower', 'feedinPower', 'loadsPower', 'gridConsumptionPower', 'batChargePower', 'batDischargePower', 'pvPower', 'meterPower2'],
            begin: beginDate.getTime(),
            end: endDate.getTime()
          };

          const foxessResp = await fetch("https://www.foxesscloud.com" + path, {
            method: "POST",
            headers,
            body: JSON.stringify(body)
          });

          if (!foxessResp.ok) {
            console.log(`fetch-demand: FoxESS API error for ${dayStr} site ${battery.site_id}:`, foxessResp.status);
            continue;
          }

          const foxessData = await foxessResp.json();
          const result = foxessData?.result?.[0]?.datas || [];

          for (const entry of result) {
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
                time,
                site_id: battery.site_id,
              });
            }
          }
        }

        if (intervals.length === 0) {
          console.log(`fetch-demand: no intervals for site ${battery.site_id}`);
          continue;
        }

        const upsertResp = await client.from("historic_energy_data").upsert(intervals, {
          onConflict: ["period_end", "variable"],
        });

        if (upsertResp.error) {
          errors.push(`Upsert error for site ${battery.site_id}: ${upsertResp.error.message}`);
        } else {
          totalIntervals += intervals.length;
          console.log(`fetch-demand: upserted ${intervals.length} intervals for site ${battery.site_id}`);
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
