/**
 * Classifier: translates optimiser output (half-hour slots) into FoxESS v3
 * schedule groups.
 *
 * This deliberately mirrors `app/services/foxess.py::classify_optimiser_output`
 * and its post-processing (drop remain mode → split at midnight → merge to
 * maxGroups-1 → append remain). The Python path is the validated one (a manual
 * preview/push uses it), so the cron path must produce byte-identical groups.
 * Parity is locked by `classify-schedule_test.ts` against a golden fixture that
 * the Python implementation also asserts against.
 *
 * Modes: SelfUse, ForceCharge, ForceDischarge, Feedin
 */

export interface OptimiserSlot {
  period_end: string; // ISO timestamp (UTC)
  net_battery_kwh: number;
  soc_pct: number;
  grid_export_kwh: number;
  grid_import_kwh: number;
  demand?: number;
  pv_estimate?: number;
  price: number;
  /** True where the price is a backfilled 7-day average, not a published rate. */
  is_synthetic?: boolean;
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
  /** Battery capacity in kWh (kept for compatibility; sizing uses soc_pct) */
  capacityKwh: number;
  /** Minimum SOC percentage (from battery config) */
  minSocPct: number;
  /** Maximum SOC percentage (from battery config) */
  maxSocPct: number;
  /** Device rated power in watts (upper bound for fdPwr) */
  ratedPowerW: number;
  /** Max groups the caller may push, INCLUDING the remain-mode group */
  maxGroups: number;
  /** Device-supported work modes (unused by the pure classifier) */
  supportedModes: string[];
  /** IANA timezone for the device (default: Europe/London) */
  localTimezone?: string;
  /**
   * Max instruction window in hours (default: 24). FoxESS schedule period
   * times have no date, so instructions spanning more than 24h duplicate
   * clock times and get rejected by the API. The optimiser still plans over
   * its full horizon; this caps what gets pushed.
   */
  maxHours?: number;
}

const THRESHOLD_DEFAULT = 0.05;

function classifySlot(slot: OptimiserSlot, threshold: number): string {
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

/** Round a SOC % up to the nearest 5% (capped 0-100). Mirrors Python. */
export function roundSocUp(v: number): number {
  return Math.min(100, Math.max(0, Math.ceil(v / 5.0) * 5));
}

/** Round a SOC % down to the nearest 5% (capped 0-100). Mirrors Python. */
export function roundSocDown(v: number): number {
  return Math.min(100, Math.max(0, Math.floor(v / 5.0) * 5));
}

/** Round a kW value up to the nearest 100W, minimum 100W. Mirrors Python. */
export function roundPowerW(kw: number): number {
  return Math.max(100, Math.ceil((kw * 1000) / 100.0) * 100);
}

function localParts(date: Date, tz: string): { hour: number; minute: number } {
  // hourCycle "h23" is required: hour12:false lets V8/Deno resolve midnight to
  // hour "24", emitting startHour: 24 which the FoxESS API rejects.
  const fmt = new Intl.DateTimeFormat("en-GB", {
    timeZone: tz,
    hour: "numeric",
    minute: "numeric",
    hourCycle: "h23",
  });
  const parts = fmt.formatToParts(date);
  const get = (type: string) => parseInt(parts.find((p) => p.type === type)?.value || "0", 10);
  return { hour: get("hour"), minute: get("minute") };
}

/** Group consecutive same-mode slots into contiguous blocks. */
function groupConsecutive(
  slots: { mode: string; index: number }[]
): { mode: string; start: number; end: number }[] {
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
 * Classify optimiser slots into FoxESS groups (no merging — like the Python
 * `classify_optimiser_output`). Per-group force params are sized to what the
 * optimiser actually scheduled, not blasted at rated power to 100%/min SOC.
 */
export function classifySchedule(
  slots: OptimiserSlot[],
  config: ClassifierConfig,
  fromTime?: Date
): FoxESSGroup[] {
  const threshold = config.threshold || THRESHOLD_DEFAULT;
  const maxHours = config.maxHours ?? 24;

  // Window bounds in ms (UTC). Groups are clipped to [fromTime, fromTime+maxHours).
  const windowStartMs = fromTime ? fromTime.getTime() : null;
  const windowEndMs = windowStartMs !== null ? windowStartMs + maxHours * 60 * 60 * 1000 : null;

  // Keep slots that overlap the window: some time after fromTime and starting
  // before the window end (keeps the slot containing "now" and the one that
  // straddles the cutoff, so both can be clipped exactly).
  let relevant = slots;
  if (windowStartMs !== null) {
    relevant = slots.filter((s) => {
      const endMs = new Date(s.period_end).getTime();
      const startMs = endMs - 30 * 60 * 1000;
      if (endMs <= windowStartMs) return false;
      if (windowEndMs !== null && startMs >= windowEndMs) return false;
      return true;
    });
  }

  if (relevant.length === 0) return [];

  const classified = relevant.map((slot, i) => ({
    slot,
    mode: classifySlot(slot, threshold),
    index: i,
  }));
  const consecutive = groupConsecutive(classified);

  const tz = config.localTimezone || "Europe/London";
  const out: FoxESSGroup[] = [];

  for (const g of consecutive) {
    const groupSlots = relevant.slice(g.start, g.end + 1);
    const startPeriodEnd = new Date(relevant[g.start].period_end);
    const endPeriodEnd = new Date(relevant[g.end].period_end);

    let startMs = startPeriodEnd.getTime() - 30 * 60 * 1000;
    let endMs = endPeriodEnd.getTime();
    if (windowStartMs !== null) startMs = Math.max(startMs, windowStartMs);
    if (windowEndMs !== null) endMs = Math.min(endMs, windowEndMs);
    if (endMs <= startMs) continue;

    // Duration of the CLIPPED group (a group clipped at its start has less time
    // to move the scheduled energy, so power must be sized up).
    const durationH = Math.max((endMs - startMs) / 3_600_000, 0.5 / 60.0);

    // Per-group force params — size to what the optimiser scheduled.
    let minSoc = config.minSocPct;
    let maxSoc = config.maxSocPct;
    let powerW = config.ratedPowerW;
    if (g.mode === "ForceCharge") {
      // maxSoc = highest SOC this charge period reaches (rounded up 5%)
      maxSoc = Math.min(config.maxSocPct, roundSocUp(Math.max(...groupSlots.map((s) => s.soc_pct))));
      const energy = groupSlots.reduce((a, s) => a + s.net_battery_kwh, 0);
      powerW = Math.min(config.ratedPowerW, roundPowerW(energy / durationH));
    } else if (g.mode === "ForceDischarge") {
      // fdSoc = lowest SOC reached (rounded DOWN 5%) so reserve is kept for
      // SelfUse after the forced discharge ends
      minSoc = Math.max(config.minSocPct, roundSocDown(Math.min(...groupSlots.map((s) => s.soc_pct))));
      const energy = groupSlots.reduce((a, s) => a - s.net_battery_kwh, 0);
      powerW = Math.min(config.ratedPowerW, roundPowerW(energy / durationH));
    }

    // Mirrors Python _build_v3_period.
    const extraParam: Record<string, number> = { minSocOnGrid: Math.round(minSoc) };
    if (g.mode === "ForceCharge") {
      // fdSoc doubles as the device's "Charging cut-off"; the FoxESS reference
      // library defaults it to maxSoc (differing values show a wrong cutoff).
      extraParam.maxSoc = Math.round(maxSoc);
      extraParam.fdSoc = Math.round(maxSoc);
      extraParam.fdPwr = Math.trunc(powerW);
    } else if (g.mode === "ForceDischarge") {
      extraParam.fdSoc = Math.round(minSoc);
      extraParam.fdPwr = Math.trunc(powerW);
    }

    const sp = localParts(new Date(startMs), tz);
    const ep = localParts(new Date(endMs), tz);

    out.push({
      startHour: sp.hour,
      startMinute: sp.minute,
      endHour: ep.hour,
      endMinute: ep.minute,
      workMode: g.mode,
      isRemainMode: false,
      extraParam,
    });
  }

  return out;
}

/**
 * Merge groups down to fit the device limit. Mirrors Python `_merge_groups`:
 * prefer absorbing SelfUse, then earliest position.
 */
export function mergeGroups(groups: FoxESSGroup[], maxGroups: number): FoxESSGroup[] {
  if (groups.length <= maxGroups) return groups;

  const merged = [...groups];

  while (merged.length > maxGroups) {
    let bestIdx = 0;
    let bestScore = Infinity;
    for (let i = 0; i < merged.length; i++) {
      const isSelfUse = merged[i].workMode === "SelfUse" ? 0 : 100;
      const score = isSelfUse + i; // prefer SelfUse, then earliest
      if (score < bestScore) {
        bestScore = score;
        bestIdx = i;
      }
    }

    // Merge into the neighbour (prefer the one before, else after)
    const target = bestIdx > 0 ? bestIdx - 1 : bestIdx + 1;
    if (target < 0 || target >= merged.length) break;

    // Direction-aware: merging group `bestIdx` into `target` must WIDEN target.
    // The old code always overwrote target.end, so merging index 0 into index 1
    // set its end to the (earlier) candidate end → end before start.
    if (target < bestIdx) {
      merged[target].endHour = merged[bestIdx].endHour;
      merged[target].endMinute = merged[bestIdx].endMinute;
    } else {
      merged[target].startHour = merged[bestIdx].startHour;
      merged[target].startMinute = merged[bestIdx].startMinute;
    }
    merged.splice(bestIdx, 1);
  }

  return merged;
}

/**
 * Full pipeline used by the cron push, mirroring Python `classify_and_push`:
 * classify → drop groups matching the remain mode → split at midnight → merge
 * to maxGroups-1 (leaving room) → append the remain-mode group.
 */
export function prepareScheduleGroups(
  slots: OptimiserSlot[],
  config: ClassifierConfig,
  fromTime: Date | undefined,
  remainMode: string
): FoxESSGroup[] {
  const maxGroups = config.maxGroups || 8;
  const roomForInstructions = Math.max(1, maxGroups - 1);

  let groups = classifySchedule(slots, config, fromTime);
  groups = groups.filter((g) => g.workMode !== remainMode);
  groups = splitGroupsAtMidnight(groups);
  if (groups.length > roomForInstructions) {
    groups = mergeGroups(groups, roomForInstructions);
  }
  groups.push(buildRemainModeGroup(remainMode, config.minSocPct));
  return groups;
}

/** Split any group that spans midnight into two groups (one per day). */
export function splitGroupsAtMidnight(groups: FoxESSGroup[]): FoxESSGroup[] {
  const out: FoxESSGroup[] = [];
  for (const g of groups) {
    const startM = g.startHour * 60 + g.startMinute;
    const endM = g.endHour * 60 + g.endMinute;
    if (endM <= startM) {
      out.push({ ...g, endHour: 23, endMinute: 59 });
      out.push({ ...g, startHour: 0, startMinute: 0 });
    } else {
      out.push(g);
    }
  }
  return out;
}

/** Full-day (00:00-23:59) remain-mode group. Must be included in every push. */
export function buildRemainModeGroup(remainMode: string, minSocPct: number): FoxESSGroup {
  return {
    startHour: 0,
    startMinute: 0,
    endHour: 23,
    endMinute: 59,
    workMode: remainMode,
    isRemainMode: true,
    extraParam: { minSocOnGrid: Math.round(minSocPct) },
  };
}
