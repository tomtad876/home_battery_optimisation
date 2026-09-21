import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.43.4";
import { decryptProviderConfig } from "../shared/encryption.ts";

// Octopus Kraken GraphQL. Auth: developer API key -> obtainKrakenToken -> JWT.
const STANDARD_URL = "https://api.octopus.energy/v1/graphql/";
const BACKEND_URL = "https://api.backend.octopus.energy/v1/graphql/";

interface OctopusCredentials {
  octopus_api_key?: string;
  octopus_account_number?: string;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function gql(url: string, query: string, token?: string): Promise<any> {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: token } : {}) },
    body: JSON.stringify({ query }),
  });
  if (!resp.ok) throw new Error(`Octopus HTTP ${resp.status}`);
  const body = await resp.json();
  if (body?.errors) throw new Error(`Octopus GraphQL: ${JSON.stringify(body.errors).slice(0, 300)}`);
  return body?.data;
}

async function obtainToken(apiKey: string): Promise<string> {
  const data = await gql(STANDARD_URL, `mutation { obtainKrakenToken(input: { APIKey: "${apiKey}" }) { token } }`);
  const token = data?.obtainKrakenToken?.token;
  if (!token) throw new Error("Octopus: no token returned (check the API key)");
  return token;
}

/** Find the property id(s) for an account. */
async function getPropertyIds(token: string, accountNumber: string): Promise<string[]> {
  const data = await gql(STANDARD_URL, `query { properties(accountNumber: "${accountNumber}") { id } }`, token);
  return (data?.properties ?? []).map((p: { id: string }) => p.id);
}

/** Discover the heat-pump controller euid for a property. */
async function findEuid(token: string, accountNumber: string, propertyId: string): Promise<string | null> {
  const data = await gql(
    BACKEND_URL,
    `query { heatPumpControllersAtLocation(accountNumber: "${accountNumber}", propertyId: "${propertyId}") { controller { euid } } }`,
    token,
  );
  return data?.heatPumpControllersAtLocation?.[0]?.controller?.euid ?? null;
}

const num = (v: unknown) => (v == null || v === "" ? null : Number(v));

function pickWaterZone(statusZones: any[], configZones: any[]): { mode: string | null; setpoint: number | null } {
  const waterCodes = new Set(
    (configZones ?? [])
      .filter((z: any) => /water/i.test(z?.configuration?.zoneType ?? ""))
      .map((z: any) => z?.configuration?.code),
  );
  const zone = (statusZones ?? []).find((z: any) => waterCodes.has(z?.zone));
  const rawSetpoint = num(zone?.telemetry?.setpointInCelsius);
  // Some installations report sentinel values (e.g. -300) when unset.
  const setpoint = rawSetpoint != null && rawSetpoint >= 0 && rawSetpoint <= 100 ? rawSetpoint : null;
  return {
    mode: zone?.telemetry?.mode ?? null,
    setpoint,
  };
}

serve(async (_req: Request) => {
  console.log("fetch-heatpump: invoked");
  try {
    const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    const encryptionKey = Deno.env.get("PROVIDER_CONFIG_ENCRYPTION_KEY");
    if (!supabaseKey) throw new Error("SUPABASE_SERVICE_ROLE_KEY not set");
    if (!encryptionKey) throw new Error("PROVIDER_CONFIG_ENCRYPTION_KEY not set");

    const client = createClient(Deno.env.get("SUPABASE_URL")!, supabaseKey);

    const { data: batteries, error: battErr } = await client
      .from("batteries")
      .select("id, site_id, provider_config")
      .not("provider_config", "is", null);
    if (battErr) throw new Error(`Failed to fetch batteries: ${battErr.message}`);
    if (!batteries || batteries.length === 0) {
      return json({ success: true, message: "No batteries configured", rows: 0 });
    }

    let rows = 0;
    const errors: string[] = [];

    for (const battery of batteries) {
      const config: OctopusCredentials = await decryptProviderConfig(battery.provider_config, encryptionKey);
      const apiKey = config?.octopus_api_key;
      const account = config?.octopus_account_number;
      if (!apiKey || !account) {
        continue; // no Octopus credentials for this site
      }

      try {
        const token = await obtainToken(apiKey);

        // euid: cached in heat_pumps, else discover and store.
        let euid: string | null = null;
        let propertyId: string | null = null;
        const { data: cached } = await client
          .from("heat_pumps")
          .select("euid")
          .eq("site_id", battery.site_id)
          .limit(1)
          .maybeSingle();
        euid = cached?.euid ?? null;

        if (!euid) {
          for (const pid of await getPropertyIds(token, account)) {
            const found = await findEuid(token, account, pid);
            if (found) {
              euid = found;
              propertyId = pid;
              break;
            }
          }
          if (!euid) {
            errors.push(`No heat pump found for site ${battery.site_id}`);
            continue;
          }
          await client.from("heat_pumps").insert({ site_id: battery.site_id, euid, property_id: propertyId });
        }

        const data = await gql(
          BACKEND_URL,
          `query {
            heatPumpControllerStatus(accountNumber: "${account}", euid: "${euid}") {
              zones { zone telemetry { setpointInCelsius mode relaySwitchedOn heatDemand retrievedAt } }
            }
            heatPumpLivePerformance(accountNumber: "${account}", euid: "${euid}") {
              coefficientOfPerformance heatOutput { value unit } powerInput { value unit } outdoorTemperature { value unit } readAt
            }
            heatPumpLifetimePerformance(accountNumber: "${account}", euid: "${euid}") {
              seasonalCoefficientOfPerformance heatOutput { value unit } energyInput { value unit } readAt
            }
            heatPumpControllerConfiguration(accountNumber: "${account}", euid: "${euid}") {
              heatPump { model }
              zones { configuration { code zoneType } }
            }
          }`,
          token,
        );

        const live = data?.heatPumpLivePerformance;
        const lifetime = data?.heatPumpLifetimePerformance;
        const readAt = live?.readAt ?? lifetime?.readAt;
        if (!readAt) {
          errors.push(`No live/lifetime data for site ${battery.site_id}`);
          continue;
        }

        const statusZones = data?.heatPumpControllerStatus?.zones ?? [];
        const configZones = data?.heatPumpControllerConfiguration?.zones ?? [];
        const water = pickWaterZone(statusZones, configZones);

        const row = {
          site_id: battery.site_id,
          read_at: readAt,
          power_input_kw: num(live?.powerInput?.value),
          heat_output_kw: num(live?.heatOutput?.value),
          cop: num(live?.coefficientOfPerformance),
          outdoor_temp_c: num(live?.outdoorTemperature?.value),
          lifetime_energy_input_kwh: num(lifetime?.energyInput?.value),
          lifetime_heat_output_kwh: num(lifetime?.heatOutput?.value),
          lifetime_scop: num(lifetime?.seasonalCoefficientOfPerformance),
          water_mode: water.mode,
          water_setpoint_c: water.setpoint,
          zones: statusZones,
        };

        const up = await client.from("heat_pump_data").upsert(row, { onConflict: "site_id,read_at" });
        if (up.error) errors.push(`Upsert error for site ${battery.site_id}: ${up.error.message}`);
        else rows += 1;
      } catch (e) {
        errors.push(`Error for site ${battery.site_id}: ${(e as Error).message}`);
      }
    }

    return json({ success: errors.length === 0, rows, sites_processed: batteries.length, errors: errors.length ? errors : undefined });
  } catch (error) {
    return json({ error: (error as Error).message }, 500);
  }
});
