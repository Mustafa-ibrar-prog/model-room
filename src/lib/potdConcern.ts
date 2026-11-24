import type { LivePropPick } from "@/server/markets/potdPick";

const avg = (x: number) => x.toFixed(1);

/**
 * The one thing most worth knowing before trusting this pick, from what is actually on the card. Context the model
 * doesn't use (injury report, history) is said to be context; nothing here claims to have moved the projection.
 */
export function mainConcern(p: LivePropPick): string {
  const own = p.injuries?.team.find((x) => x.name === p.player);
  if (own && /questionable|doubtful/i.test(own.status)) return `he is listed ${own.status.toLowerCase()} on the injury report`;
  const mates = (p.injuries?.team ?? []).filter((x) => x.name !== p.player && /out|doubtful/i.test(x.status));
  if (mates.length) return `${mates.map((x) => x.name).join(", ")} listed ${mates.length > 1 ? "out or doubtful" : mates[0].status.toLowerCase()}; model ${p.modelVersion} doesn't read the injury report`;
  if (p.toward > 0.1) return `${Math.round(p.toward * 100)}% of the projection comes from adjustments toward this side`;
  if (p.game && p.game.p15 >= 0.35) return `a ${Math.round(p.game.p15 * 100)}% chance either team wins by 15+, which cuts starters' minutes`;
  const h = p.history.thisSeason;
  if (h && h.games >= 5) {
    const rate = h.hits / h.games;
    if (p.side === "over" && rate < 0.5) return `he has reached ${p.contract}+ in only ${h.hits} of ${h.games} games this season`;
    if (p.side === "under" && rate > 0.5) return `he has reached ${p.contract}+ in ${h.hits} of ${h.games} games this season`;
  }
  const r = p.form.range;
  if (r && ((p.side === "over" && p.line > r.hi) || (p.side === "under" && p.line < r.lo))) return `the line sits outside his typical range (${avg(r.lo)}–${avg(r.hi)})`;
  return "none flagged";
}
