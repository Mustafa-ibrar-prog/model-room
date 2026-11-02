import { Section } from "@/components/ui/primitives";

const STEPS = [
  {
    title: "Collect the inputs",
    body: "Schedules, results, play-by-play, posted lines and official injury reports are pulled in and checked before anything is modeled.",
  },
  {
    title: "Rate every team",
    body: "Each team gets an offensive, defensive and pace rating measured in points against an average opponent.",
  },
  {
    title: "Adjust for availability",
    body: "Players ruled out or limited move the ratings by an estimate of what that player is worth.",
  },
  {
    title: "Project the game",
    body: "Ratings, home field, rest and travel produce a projected score, spread and total for each matchup.",
  },
  {
    title: "Compare with the market",
    body: "The projection is set against the current line. The difference is the edge, and only edges of a point or more are flagged.",
  },
];

export function HowItWorks() {
  return (
    <Section
      id="how-it-works"
      title="How it works"
      intro="The same five steps run for every NFL and NBA game. The engines behind them are in development, so the boards show demo data for now."
    >
      <ol className="grid gap-px overflow-hidden rounded-xl border border-navy-700 bg-navy-700 sm:grid-cols-2 lg:grid-cols-5">
        {STEPS.map((s, i) => (
          <li key={s.title} className="bg-navy-900 p-5">
            <span className="font-display text-3xl font-700 text-model/80">{i + 1}</span>
            <h3 className="mt-2 font-display text-xl font-600 text-ink">{s.title}</h3>
            <p className="mt-2 text-[0.93rem] leading-relaxed text-mute">{s.body}</p>
          </li>
        ))}
      </ol>
    </Section>
  );
}
