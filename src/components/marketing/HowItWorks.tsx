import { Section } from "@/components/ui/primitives";

const STEPS = [
  {
    title: "Collect and check the data",
    body: "Schedules, results, box scores, play-by-play and injury reports are downloaded, then checked for gaps, duplicates and conflicts between sources.",
  },
  {
    title: "Rate every team",
    body: "NBA teams get offense, defense and pace ratings per 100 possessions. NFL teams get EPA per play ratings, with garbage time down-weighted. Both adjust for opponents and weight recent games more.",
  },
  {
    title: "Adjust for the situation",
    body: "Rest, back-to-backs, home field and, for the NFL, the starting quarterback move the projection. Each adjustment is fitted on past seasons.",
  },
  {
    title: "Project the game",
    body: "Ratings produce projected scores. The line, total and win probability come from those scores and the model's measured error.",
  },
  {
    title: "Compare with the market",
    body: "The projection is shown next to the sportsbook line, and the difference between them is shown as a number. A difference is not a betting edge: in the NFL seasons tested (2023–25) the sportsbook line was closer to the final score than the model, and the largest spread differences picked the side that covered less than half the time.",
  },
];

export function HowItWorks() {
  return (
    <Section
      id="how-it-works"
      title="How it works"
      intro="The same five steps run for every NFL and NBA game. Each model version is tested on seasons it never saw before its projections are shown."
    >
      {/* Phones: swipe through the steps. Wider: a grid. */}
      <ol className="-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-2 sm:mx-0 sm:grid sm:snap-none sm:gap-px sm:overflow-hidden sm:rounded-xl sm:border sm:border-navy-700 sm:bg-navy-700 sm:px-0 sm:pb-0 sm:grid-cols-2 lg:grid-cols-5">
        {STEPS.map((s, i) => (
          <li key={s.title} className="w-[78%] shrink-0 snap-start rounded-xl border border-navy-700 bg-navy-900 p-5 sm:w-auto sm:rounded-none sm:border-0">
            <span className="font-display text-3xl font-700 text-model/80">{i + 1}</span>
            <h3 className="mt-2 font-display text-xl font-600 text-ink">{s.title}</h3>
            <p className="mt-2 text-[0.93rem] leading-relaxed text-mute">{s.body}</p>
          </li>
        ))}
      </ol>
    </Section>
  );
}
