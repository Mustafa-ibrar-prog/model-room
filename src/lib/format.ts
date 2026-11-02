/** Formatting helpers for betting numbers. Pure functions, safe anywhere. */

export function formatSpread(n: number): string {
  if (n === 0) return "PK";
  return n > 0 ? `+${fmt(n)}` : fmt(n);
}

export function formatEdge(n: number): string {
  return n > 0 ? `+${fmt(n)}` : fmt(n);
}

export function formatNumber(n: number, digits = 1): string {
  return n.toFixed(digits);
}

export function formatPct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

export function formatPrice(n: number): string {
  return n === 0 ? "$0" : `$${n.toFixed(2)}`;
}

function fmt(n: number): string {
  return Number.isInteger(n) ? n.toFixed(1) : String(Math.round(n * 10) / 10);
}
