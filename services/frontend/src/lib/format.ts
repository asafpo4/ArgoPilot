const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * "2026-11-19" -> "Thu 19 Nov".
 * The plan dates are plain local dates. The string is split into parts and only UTC getters are used,
 * so the machine's time zone can never shift the day. An invalid string is returned unchanged.
 */
export function formatPlanDate(date: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!m) return date;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const at = new Date(Date.UTC(y, mo - 1, d));
  if (at.getUTCFullYear() !== y || at.getUTCMonth() !== mo - 1 || at.getUTCDate() !== d) return date;
  return `${WEEKDAYS[at.getUTCDay()]} ${d} ${MONTHS[mo - 1]}`;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** Age of the forecast as text, e.g. "fetched 20 minutes ago". Null if the timestamp is invalid or in the future. */
export function forecastAge(fetchedAt: string, nowMs: number): string | null {
  const t = Date.parse(fetchedAt);
  if (Number.isNaN(t) || t > nowMs) return null;
  const minutes = Math.floor((nowMs - t) / 60_000);
  if (minutes < 1) return "fetched just now";
  if (minutes < 60) return `fetched ${plural(minutes, "minute")} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `fetched ${plural(hours, "hour")} ago`;
  return `fetched ${plural(Math.floor(hours / 24), "day")} ago`;
}

/** Same as forecastAge, with the current time. Kept apart so pages stay free of clock reads. */
export function forecastAgeNow(fetchedAt: string): string | null {
  return forecastAge(fetchedAt, Date.now());
}

/** 2.4 -> "2.4 mm", 3 -> "3 mm" (at most 2 decimals). */
export function formatMm(n: number): string {
  return `${Number(n.toFixed(2)).toLocaleString("en-US")} mm`;
}

export function formatLitres(n: number): string {
  return `${Math.round(n).toLocaleString("en-US")} L`;
}

export function formatMinutes(n: number): string {
  return n === 1 ? "1 minute" : `${n} minutes`;
}

/** "after_cycle" -> "After cycle" */
export function stageLabel(stage: string): string {
  const text = stage.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
