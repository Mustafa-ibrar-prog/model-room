const PROVIDER: Record<string, string> = { polymarket_us: "Polymarket US", kalshi: "Kalshi" };

export const providerName = (p: string) => (p.startsWith("manual:") ? p.slice(7) : (PROVIDER[p] ?? p));
