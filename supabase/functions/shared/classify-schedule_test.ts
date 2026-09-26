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
