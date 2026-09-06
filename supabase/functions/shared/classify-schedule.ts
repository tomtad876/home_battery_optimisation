/**
 * Classifier: translates optimiser output (48 half-hour slots) into
 * FoxESS v3 schedule groups (device-limited count).
 *
 * Modes: SelfUse, ForceCharge, ForceDischarge, Feedin
 */

export interface OptimiserSlot {
  period_end: string; // ISO timestamp
  net_battery_kwh: number;
  soc_pct: number;
  grid_export_kwh: number;
  grid_import_kwh: number;
  demand: number;
  pv_estimate: number;
  price: number;
}

export interface FoxESSGroup {
  startHour: number;
  startMinute: number;
  endHour: number;
  endMinute: number;
  workMode: string;
  isRemainMode: boolean;
  extraParam: Record<string, number>;
}

export interface ClassifierConfig {
  /** Minimum absolute net_battery_kwh to trigger a mode change */
  threshold: number;
  /** Battery capacity in kWh — used for SOC-based param calculations */
  capacityKwh: number;
  /** Minimum SOC percentage (from battery config) */
  minSocPct: number;
  /** Maximum SOC percentage (from battery config) */
  maxSocPct: number;
  /** Device rated power in watts (for fdPwr) */
  ratedPowerW: number;
  /** Max groups device supports (from maxGroupCount) */
  maxGroups: number;
  /** Device-supported work modes (from scheduler properties) */
  supportedModes: string[];
  /** IANA timezone for the device (default: Europe/London) */
  localTimezone?: string;
}

const THRESHOLD_DEFAULT = 0.05;

function classifySlot(
  slot: OptimiserSlot,
  threshold: number
): string {
  const net = slot.net_battery_kwh;
  const exportKwh = slot.grid_export_kwh ?? 0;
  const importKwh = slot.grid_import_kwh ?? 0;
  const price = slot.price ?? 0;

  if (net > threshold) {
    // Charging — from grid (needs ForceCharge) or solar surplus (SelfUse)?
    if (importKwh > threshold) {
      return "ForceCharge";
    }
    return "SelfUse";
  }
  if (net < -threshold) {
    // Discharging — exporting to grid (ForceDischarge) or covering demand (SelfUse)?
    if (exportKwh > threshold) {
      return "ForceDischarge";
    }
    return "SelfUse";
  }
  // Net near zero — battery idle, but solar exporting to grid
  if (exportKwh > threshold) {
    // During negative prices, prefer ForceCharge over Feedin —
    // we're being paid to charge, so keep the battery topped up.
    if (price < 0) {
      return "ForceCharge";
    }
    return "Feedin";
  }
  return "SelfUse";
}

/**
 * Group consecutive same-mode slots into contiguous blocks.
 */
function groupConsecutive(slots: { mode: string; index: number }[]): { mode: string; start: number; end: number }[] {
  if (slots.length === 0) return [];

  const groups: { mode: string; start: number; end: number }[] = [];
  let current = { mode: slots[0].mode, start: slots[0].index, end: slots[0].index };

  for (let i = 1; i < slots.length; i++) {
    if (slots[i].mode === current.mode && slots[i].index === current.end + 1) {
      current.end = slots[i].index;
    } else {
      groups.push(current);
      current = { mode: slots[i].mode, start: slots[i].index, end: slots[i].index };
    }
  }
  groups.push(current);
  return groups;
}

/**
 * Merge groups down to fit within the device's maxGroupCount.
 * Strategy: merge adjacent groups, preferring to absorb SelfUse into neighbours.
 */
function mergeToLimit(
  groups: { mode: string; start: number; end: number; slotCount: number }[],
  maxGroups: number
): { mode: string; start: number; end: number; slotCount: number }[] {
  if (groups.length <= maxGroups) return groups;

  // Sort by slotCount ascending so we merge the smallest groups first
  const merged = [...groups];

  while (merged.length > maxGroups) {
    // Find the best merge: prefer absorbing SelfUse, otherwise smallest group
    let bestIdx = 0;
    let bestScore = Infinity;

    for (let i = 0; i < merged.length; i++) {
      const group = merged[i];
      // Score: SelfUse groups get bonus (easier to absorb), otherwise use slot count
      const isSelfUse = group.mode === "SelfUse" ? 0 : 100;
      const score = isSelfUse + group.slotCount;
      if (score < bestScore) {
        bestScore = score;
        bestIdx = i;
      }
    }

    // Merge into the larger of its neighbours
    const targetIdx = bestIdx > 0 ? bestIdx - 1 : bestIdx + 1;
    if (targetIdx < 0 || targetIdx >= merged.length) break;

    merged[targetIdx].end = merged[bestIdx].end;
    merged[targetIdx].slotCount += merged[bestIdx].slotCount;
    // If merging different modes, take the neighbour's mode
    merged.splice(bestIdx, 1);
  }

  return merged;
}

/**
 * Build extraParam for a group based on its mode and config.
 */
function buildExtraParam(
  mode: string,
  config: ClassifierConfig
): Record<string, number> {
  const minSoc = Math.round(config.minSocPct);
  const params: Record<string, number> = {
    minSocOnGrid: minSoc,
  };

  switch (mode) {
    case "ForceCharge": {
      params.maxSoc = Math.round(config.maxSocPct);
      params.fdSoc = minSoc;
      params.fdPwr = config.ratedPowerW;
      break;
    }
    case "ForceDischarge": {
      params.fdSoc = minSoc;
      params.fdPwr = config.ratedPowerW;
      break;
    }
    case "Feedin": {
      // Feedin prioritises export — no extra params needed beyond minSocOnGrid
      break;
    }
    case "SelfUse": {
      // Self-managing, no extra params
      break;
    }
  }

  return params;
}

/**
 * Convert an optimiser schedule into FoxESS v3 schedule groups.
 *
 * @param slots - Array of optimiser output records (typically 48 half-hour periods)
 * @param config - Classifier configuration
 * @param fromTime - Only include periods at or after this time (for background runs)
 * @returns Array of FoxESS schedule groups, capped at config.maxGroups
 */
export function classifySchedule(
  slots: OptimiserSlot[],
  config: ClassifierConfig,
  fromTime?: Date
): FoxESSGroup[] {
  const threshold = config.threshold || THRESHOLD_DEFAULT;

  // Filter to future slots only if fromTime provided
  let relevant = slots;
  if (fromTime) {
    relevant = slots.filter((s) => new Date(s.period_end) > fromTime);
  }

  if (relevant.length === 0) return [];

  // 1. Classify each slot
  const classified = relevant.map((slot, i) => ({
    slot,
    mode: classifySlot(slot, threshold),
    index: i,
  }));

  // 2. Group consecutive same-mode slots
  const consecutive = groupConsecutive(classified);

  // 3. Add slot counts for merge scoring
  const withCounts = consecutive.map((g) => ({
    ...g,
    slotCount: g.end - g.start + 1,
  }));

  // 4. Merge down to device limit
  const merged = mergeToLimit(withCounts, config.maxGroups);

  // 5. Build FoxESS groups (in local time — FoxESS device uses device-local timezone)
  const tz = config.localTimezone || "Europe/London";
  return merged.map((group) => {
    const startSlot = relevant[group.start];
    const endSlot = relevant[group.end];

    const startPeriodEnd = new Date(startSlot.period_end);
    const startTime = new Date(startPeriodEnd.getTime() - 30 * 60 * 1000); // back 30 min
    const endPeriodEnd = new Date(endSlot.period_end);

    // Convert to local time using Intl
    const fmt = new Intl.DateTimeFormat("en-GB", {
      timeZone: tz,
      hour: "numeric",
      minute: "numeric",
      hour12: false,
    });
    const startParts = fmt.formatToParts(startTime);
    const endParts = fmt.formatToParts(endPeriodEnd);
    const getVal = (parts: Intl.DateTimeFormatPart[], type: string) =>
      parseInt(parts.find((p) => p.type === type)?.value || "0", 10);

    return {
      startHour: getVal(startParts, "hour"),
      startMinute: getVal(startParts, "minute"),
      endHour: getVal(endParts, "hour"),
      endMinute: getVal(endParts, "minute"),
      workMode: group.mode,
      isRemainMode: false,
      extraParam: buildExtraParam(group.mode, config),
    };
  });
}
