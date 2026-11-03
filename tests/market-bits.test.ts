/** The quote shown per exchange on a line: its usable quote if any, else the latest flagged one; never invented. */
import { describe, expect, it } from "vitest";
import { lineLabel, quoteBy } from "@/components/market/bits";
import type { PropLineView } from "@/types/props";

const q = (provider: string, usable: boolean, capturedAt: string, mid: number | null = 0.5) => ({
  provider, mid, bid: mid, ask: mid, spread: 0.02, askSize: null, usable, flags: usable ? [] : ["stale"], capturedAt,
});
const line = (quotes: PropLineView["quotes"]): PropLineView => ({ op: ">=", threshold: 50, variant: null, modelProb: 0.6, market: null, quotes, edge: null });

describe("market quotes on a line", () => {
  it("keeps Polymarket and Kalshi separate and prefers a usable quote", () => {
    const b = quoteBy(line([q("kalshi", false, "2030-01-01T10:00:00Z", 0.4), q("kalshi", true, "2030-01-01T09:00:00Z", 0.45), q("polymarket_us", false, "2030-01-01T10:00:00Z", 0.5)]));
    expect(b.kalshi?.mid).toBe(0.45);
    expect(b.polymarket_us?.usable).toBe(false);
  });
  it("shows nothing for an exchange with no quote", () => {
    expect(quoteBy(line([]))).toEqual({});
  });
  it("labels thresholds the way the contracts read", () => {
    expect(lineLabel({ op: ">=", threshold: 50, variant: null })).toBe("50+");
    expect(lineLabel({ op: ">", threshold: 49.5, variant: null })).toBe("Over 49.5");
    expect(lineLabel({ op: ">=", threshold: 15, variant: "sleeper_ppr" })).toBe("15+ Sleeper");
  });
});
