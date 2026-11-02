/**
 * Team colors for the matchup badges (primary color as hex). Official team logos are trademarks that
 * need a license, so the site shows a colored code badge instead.
 * NBA colors are the ones hoopR's ESPN data reports; NFL colors are the teams' published primaries.
 */
import type { League } from "@/types/domain";

const NFL: Record<string, string> = {
  ARI: "97233f", ATL: "a71930", BAL: "241773", BUF: "00338d", CAR: "0085ca", CHI: "0b162a", CIN: "fb4f14", CLE: "311d00",
  DAL: "003594", DEN: "fb4f14", DET: "0076b6", GB: "203731", HOU: "03202f", IND: "002c5f", JAX: "006778", KC: "e31837",
  LV: "000000", LAC: "0080c6", LA: "003594", MIA: "008e97", MIN: "4f2683", NE: "002244", NO: "d3bc8d", NYG: "0b2265",
  NYJ: "125740", PHI: "004c54", PIT: "ffb612", SF: "aa0000", SEA: "002244", TB: "d50a0a", TEN: "4b92db", WAS: "5a1414",
};

const NBA: Record<string, string> = {
  BOS: "008348", ORL: "0150b5", BKN: "000000", IND: "0c2340", LAC: "12173f", GS: "fdb927", TOR: "d91244", LAL: "552583",
  POR: "e03a3e", UTAH: "4e008e", PHI: "1d428a", CHA: "008ca8", ATL: "c8102e", NO: "0a2240", SAC: "5a2d81", MEM: "5d76a9",
  CLE: "860038", MIL: "00471b", MIN: "266092", SA: "000000", OKC: "007ac1", HOU: "ce0e2d", WSH: "e31837", CHI: "ce1141",
  DET: "1d428a", NY: "1d428a", MIA: "98002e", DAL: "0064b1", DEN: "0e2240", PHX: "29127a",
};

export function teamColor(league: League, abbr: string): string {
  return `#${(league === "nfl" ? NFL : NBA)[abbr] ?? "5b6b7d"}`;
}

/** Light text on dark team colors, dark text on light ones. */
export function teamInk(hex: string): string {
  const n = parseInt(hex.replace("#", ""), 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#14202e" : "#ffffff";
}
