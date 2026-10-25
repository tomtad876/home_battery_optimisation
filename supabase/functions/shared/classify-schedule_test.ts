/**
 * Classifier parity tests.
 *
 * `prepareScheduleGroups` (the cron/auto-push path) must produce byte-identical
 * groups to the Python reference for the same input. The fixture is generated
 * by app/services/foxess.py and asserted by both sides
 * (tests/test_classifier_parity.py and this file).
 */
import { assertEquals } from "jsr:@std/assert@1";
import {
  prepareScheduleGroups,
  mergeGroups,
  type OptimiserSlot,
  type ClassifierConfig,
  type FoxESSGroup,
} from "./classify-schedule.ts";

const fixture = JSON.parse(
  await Deno.readTextFile(new URL("./__fixtures__/classifier_parity.json", import.meta.url)),
);

for (const c of fixture.cases) {
  Deno.test(`classifier parity with Python golden fixture: ${c.name}`, () => {
    const fromTime = c.fromTime ? new Date(c.fromTime) : undefined;
    const got = prepareScheduleGroups(
      c.slots as OptimiserSlot[],
      c.config as ClassifierConfig,
      fromTime,
      c.remainMode as string,
    );
    assertEquals(got, c.expectedGroups);
  });
}

function period(
  sh: number,
  sm: number,
  eh: number,
  em: number,
  mode: string,
): FoxESSGroup {
  return {
    startHour: sh,
    startMinute: sm,
    endHour: eh,
    endMinute: em,
    workMode: mode,
    isRemainMode: false,
    extraParam: { minSocOnGrid: 20 },
  };
}

Deno.test("hold: idle while importing raises the floor instead of self-using", () => {
  // 2026-10-25: the plan said "import 0.09 kWh at -2p, SOC stays 100%".
  // This used to classify as SelfUse and get dropped as remain-equivalent,
  // so the inverter served the house from the battery and it fell to 61%.
  const slots: OptimiserSlot[] = [
    {
      period_end: "2026-10-25T15:00:00Z",
      net_battery_kwh: 0,
      soc_pct: 100,
      grid_import_kwh: 0.0865,
      grid_export_kwh: 0,
      price: -2,
    },
    {
      period_end: "2026-10-25T15:30:00Z",
      net_battery_kwh: 0,
      soc_pct: 100,
      grid_import_kwh: 0.12,
      grid_export_kwh: 0,
      price: -1.24,
    },
  ];
  const groups = prepareScheduleGroups(
    slots,
    {
      threshold: 0.05,
      capacityKwh: 5,
      minSocPct: 20,
      maxSocPct: 100,
      ratedPowerW: 3000,
      maxGroups: 8,
      supportedModes: ["SelfUse", "ForceCharge", "ForceDischarge", "Feedin"],
      localTimezone: "Europe/London",
    },
    new Date("2026-10-25T14:30:00Z"),
    "SelfUse",
  );

  assertEquals(groups.length, 2); // hold + remain
  const hold = groups[0];
  assertEquals(hold.isRemainMode, false);
  assertEquals(hold.workMode, "SelfUse");
  assertEquals(hold.extraParam.minSocOnGrid, 100);
  // A floor, not a force-charge: nothing may drive the battery.
  assertEquals(hold.extraParam.fdSoc, undefined);
  assertEquals(hold.extraParam.fdPwr, undefined);
  assertEquals(groups[1].isRemainMode, true);
});

Deno.test("hold: dropped, not merged into a forced group, when over budget", () => {
  const cfg: ClassifierConfig = {
    threshold: 0.05,
    capacityKwh: 5,
    minSocPct: 20,
    maxSocPct: 100,
    ratedPowerW: 3000,
    maxGroups: 3, // room for 2 instructions + remain
    supportedModes: ["SelfUse", "ForceCharge", "ForceDischarge", "Feedin"],
    localTimezone: "Europe/London",
  };
  const slot = (h: number, m: number, net: number, imp: number, exp: number, soc: number) => ({
    period_end: new Date(Date.UTC(2026, 9, 25, h, m)).toISOString(),
    net_battery_kwh: net,
    soc_pct: soc,
    grid_import_kwh: imp,
    grid_export_kwh: exp,
    price: 10,
  });
  const slots: OptimiserSlot[] = [
    slot(15, 0, 0, 0.2, 0, 100),   // hold
    slot(15, 30, 0, 0.2, 0, 100),  // hold
    slot(16, 0, 0, 0, 0.5, 100),   // Feedin
    slot(16, 30, 0, 0, 0.5, 100),  // Feedin
    slot(17, 0, -1.5, 0, 1.5, 70), // ForceDischarge
    slot(17, 30, -1.5, 0, 1.5, 40),
  ];
  const groups = prepareScheduleGroups(slots, cfg, new Date("2026-10-25T14:30:00Z"), "SelfUse");

  assertEquals(groups.length, 3);
  assertEquals(groups[0].workMode, "Feedin");
  // period_end 16:00 means the 15:30-16:00 slot, so Feedin starts at 15:30.
  assertEquals(groups[0].startHour, 15);
  assertEquals(groups[0].startMinute, 30); // not widened back over the hold window
  assertEquals(groups[1].workMode, "ForceDischarge");
  assertEquals(groups[2].isRemainMode, true);
});

Deno.test("merge: index 0 widens the survivor's start (not its end)", () => {
  const merged = mergeGroups(
    [period(22, 0, 23, 0, "ForceCharge"), period(23, 0, 23, 30, "ForceDischarge")],
    1,
  );
  assertEquals(merged.length, 1);
  assertEquals(merged[0].startHour, 22);
  assertEquals(merged[0].startMinute, 0);
  assertEquals(merged[0].endHour, 23);
  assertEquals(merged[0].endMinute, 30);
  assertEquals(merged[0].workMode, "ForceDischarge");
});

Deno.test("merge: prefers absorbing SelfUse", () => {
  const merged = mergeGroups(
    [
      period(1, 0, 2, 0, "ForceCharge"),
      period(2, 0, 3, 0, "SelfUse"),
      period(3, 0, 4, 0, "ForceDischarge"),
    ],
    2,
  );
  assertEquals(merged.length, 2);
  // SelfUse (index 1) is absorbed into the preceding group (index 0).
  assertEquals(merged[0].workMode, "ForceCharge");
  assertEquals(merged[0].endHour, 3);
});
