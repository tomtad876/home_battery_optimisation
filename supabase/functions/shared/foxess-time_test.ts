/**
 * FoxESS local-time parsing tests.
 *
 * The 2026-10-25 incident: history times were stored as naive local strings, so
 * the autumn fall-back hour (01:00-02:00, twice) collapsed and the second pass
 * overwrote the first. `period_end` is now timestamptz and we send real
 * instants — these cases cover the offsets the device actually emits.
 */
import { assertEquals } from "jsr:@std/assert@1";
import { foxessTimeToUtcIso } from "./foxess-time.ts";

Deno.test("foxess time: BST offset becomes UTC", () => {
  assertEquals(
    foxessTimeToUtcIso("2026-07-15 11:03:33 BST+0100"),
    "2026-07-15T10:03:33.000Z",
  );
});

Deno.test("foxess time: GMT offset is a no-op", () => {
  assertEquals(
    foxessTimeToUtcIso("2026-10-25 17:43:32 GMT+0000"),
    "2026-10-25T17:43:32.000Z",
  );
});

Deno.test("foxess time: both passes of the ambiguous hour survive", () => {
  // 01:03:32 happened twice on 2026-10-25 — one hour apart, and recognised as
  // such because the API includes the offset.
  assertEquals(
    foxessTimeToUtcIso("2026-10-25 01:03:32 BST+0100"),
    "2026-10-25T00:03:32.000Z",
  );
  assertEquals(
    foxessTimeToUtcIso("2026-10-25 01:03:32 GMT+0000"),
    "2026-10-25T01:03:32.000Z",
  );
});

Deno.test("foxess time: tolerated offset formats", () => {
  assertEquals(
    foxessTimeToUtcIso("2026-10-25 01:03:32 GMT+00:00"),
    "2026-10-25T01:03:32.000Z",
  );
  assertEquals(
    foxessTimeToUtcIso("2026-10-25 01:03:32 GMT+0000"),
    "2026-10-25T01:03:32.000Z",
  );
});

Deno.test("foxess time: unparseable input returns null", () => {
  assertEquals(foxessTimeToUtcIso("not a timestamp"), null);
  assertEquals(foxessTimeToUtcIso("2026-10-25 01:03:32"), null);
});
