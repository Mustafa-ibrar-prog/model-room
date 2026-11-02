/** Formatting helpers. Pure functions, safe anywhere. */

export function formatSpread(n: number): string {
  if (Math.abs(n) < 0.05) return "PK";
  return n > 0 ? `+${fmt(n)}` : `−${fmt(Math.abs(n))}`;
}

export function formatSigned(n: number, digits = 1): string {
  const v = Number(n.toFixed(digits));
  if (v === 0) return (0).toFixed(digits);
  return v > 0 ? `+${v.toFixed(digits)}` : `−${Math.abs(v).toFixed(digits)}`;
}

export function formatNumber(n: number, digits = 1): string {
  return n.toFixed(digits);
}

export function formatPct(p: number, digits = 0): string {
  return `${(p * 100).toFixed(digits)}%`;
}

export function formatPrice(n: number): string {
  return n === 0 ? "$0" : `$${n.toFixed(2)}`;
}

export function formatMoneyline(n: number): string {
  return n > 0 ? `+${Math.round(n)}` : `−${Math.abs(Math.round(n))}`;
}

/**
 * Who the line favors. Model Room spreads are the home team's line:
 * negative = home favored. Returns e.g. "BOS −3.5" or "Pick'em".
 */
export function favoredLine(spread: number, homeAbbr: string, awayAbbr: string): { team: string | null; text: string } {
  if (Math.abs(spread) < 0.25) return { team: null, text: "Pick'em" };
  return spread < 0
    ? { team: homeAbbr, text: `${homeAbbr} −${fmt(Math.abs(spread))}` }
    : { team: awayAbbr, text: `${awayAbbr} −${fmt(Math.abs(spread))}` };
}

const ET = "America/New_York";

export function formatKickoff(iso: string | null): string {
  if (!iso) return "Time TBD";
  const d = new Date(iso);
  const day = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: ET });
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: ET });
  return `${day}, ${time} ET`;
}

export function formatDateShort(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

export function formatTimestamp(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: ET, timeZoneName: "short" });
}

function fmt(n: number): string {
  return (Math.round(n * 10) / 10).toFixed(1);
}
