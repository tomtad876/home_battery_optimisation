/**
 * FoxESS history returns `time` as a *local* wall-clock string with an offset
 * suffix, e.g. "2026-10-25 01:03:32 GMT+0000" or "2026-07-15 11:03:33 BST+0100".
 * Storing that string in a naive timestamp column lost the offset: on the
 * autumn change 01:00-02:00 happened twice and the second pass overwrote the
 * first (2026-10-25). Convert to a real UTC instant instead.
 */
export function foxessTimeToUtcIso(raw: string): string | null {
  const m = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})\s+[A-Za-z]+\s*([+-]\d{2}):?(\d{2})$/
    .exec(raw.trim());
  if (!m) return null;
  const parsed = Date.parse(`${m[1]}T${m[2]}${m[3]}:${m[4]}`);
  return Number.isFinite(parsed) ? new Date(parsed).toISOString() : null;
}
