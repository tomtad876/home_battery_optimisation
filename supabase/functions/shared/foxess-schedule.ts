/**
 * FoxESS v3 API helpers for schedule management.
 * Uses MD5-signed requests (same pattern as fetch-demand).
 */
import { Md5 } from "npm:ts-md5";

const FOXESS_BASE_URL = "https://www.foxesscloud.com";

interface FoxESSHeaders {
  "Content-Type": string;
  signature: string;
  token: string;
  timestamp: string;
  lang: string;
}

function signHeaders(path: string, apiKey: string, timestamp: number): FoxESSHeaders {
  const signature = Md5.hashStr(`${path}\\r\\n${apiKey}\\r\\n${timestamp.toString()}`);
  return {
    "Content-Type": "application/json",
    signature,
    token: apiKey,
    timestamp: timestamp.toString(),
    lang: "en",
  };
}

async function foxessPost(
  path: string,
  apiKey: string,
  body: Record<string, unknown>
): Promise<{ ok: boolean; status: number; data: any }> {
  const ts = Date.now();
  const headers = signHeaders(path, apiKey, ts);
  const resp = await fetch(`${FOXESS_BASE_URL}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const data = await resp.json().catch(() => null);
  return { ok: resp.ok, status: resp.status, data };
}

export interface DeviceScheduleInfo {
  supported: boolean;
  enabled: boolean;
  maxGroupCount: number;
  properties: Record<string, any> | null;
}

/**
 * Query the device for scheduler support, maxGroupCount, and mode properties.
 * Combines the v1 flag check and v3 properties fetch (matching foxesscloud get_flag).
 */
export async function getDeviceScheduleInfo(
  apiKey: string,
  deviceSn: string
): Promise<DeviceScheduleInfo> {
  // 1. Check scheduler support + enable status
  const flagResp = await foxessPost(
    "/op/v1/device/scheduler/get/flag",
    apiKey,
    { deviceSN: deviceSn }
  );

  if (!flagResp.ok || flagResp.data?.result == null) {
    throw new Error(
      `Failed to get scheduler flag: HTTP ${flagResp.status}, errno ${flagResp.data?.errno}`
    );
  }

  const flagResult = flagResp.data.result;
  const supported = flagResult.support === true || flagResult.support === 1;
  const enabled = flagResult.enable === true || flagResult.enable === 1;

  if (!supported) {
    return { supported: false, enabled: false, maxGroupCount: 8, properties: null };
  }

  // 2. Get properties (maxGroupCount, available modes, param support)
  const propResp = await foxessPost(
    "/op/v3/device/scheduler/get",
    apiKey,
    { deviceSN: deviceSn }
  );

  if (!propResp.ok || propResp.data?.result == null) {
    // Fallback to defaults if properties fetch fails
    return { supported: true, enabled, maxGroupCount: 8, properties: null };
  }

  const propResult = propResp.data.result;
  return {
    supported: true,
    enabled,
    maxGroupCount: propResult.maxGroupCount ?? 8,
    properties: propResult.properties ?? null,
  };
}

/**
 * Disable the schedule on the device.
 */
export async function disableSchedule(
  apiKey: string,
  deviceSn: string
): Promise<void> {
  const resp = await foxessPost(
    "/op/v1/device/scheduler/set/flag",
    apiKey,
    { deviceSN: deviceSn, enable: 0 }
  );

  if (!resp.ok || resp.data?.errno !== 0) {
    throw new Error(
      `Failed to disable schedule: HTTP ${resp.status}, errno ${resp.data?.errno}`
    );
  }
}

/**
 * Push schedule groups to the device and enable it.
 *
 * @param groups - Array of FoxESS schedule group objects (from classifySchedule)
 */
export async function pushSchedule(
  apiKey: string,
  deviceSn: string,
  groups: Array<Record<string, any>>
): Promise<any> {
  // 1. Push groups
  const pushResp = await foxessPost(
    "/op/v3/device/scheduler/enable",
    apiKey,
    { deviceSN: deviceSn, isDefault: false, groups }
  );

  if (!pushResp.ok || pushResp.data?.errno !== 0) {
    throw new Error(
      `Failed to push schedule groups: HTTP ${pushResp.status}, errno ${pushResp.data?.errno}`
    );
  }

  // 2. Enable the schedule
  const enableResp = await foxessPost(
    "/op/v1/device/scheduler/set/flag",
    apiKey,
    { deviceSN: deviceSn, enable: 1 }
  );

  if (!enableResp.ok || enableResp.data?.errno !== 0) {
    throw new Error(
      `Failed to enable schedule: HTTP ${enableResp.status}, errno ${enableResp.data?.errno}`
    );
  }

  return pushResp.data;
}

/**
 * Full push sequence: disable existing → push new groups → enable.
 * Returns the provider response for logging.
 */
export async function sendScheduleToInverter(
  apiKey: string,
  deviceSn: string,
  groups: Array<Record<string, any>>
): Promise<{ pushed: boolean; providerResponse: any }> {
  await disableSchedule(apiKey, deviceSn);
  const response = await pushSchedule(apiKey, deviceSn, groups);
  return { pushed: true, providerResponse: response };
}
