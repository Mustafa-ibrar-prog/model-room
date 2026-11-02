import { getDailyInsights } from "@/server/data";
import { getViewer } from "@/server/viewer";
import { DemoStamp } from "@/components/ui/primitives";

export async function DailyInsights() {
  const viewer = await getViewer();
  const { data } = await getDailyInsights(viewer.tier);
  return (
    <ul className="grid gap-6 md:grid-cols-3">
      {data.map((n) => (
        <li key={n.id} className="border-l-2 border-model/60 pl-4">
          <div className="flex items-center gap-2 text-[0.8rem] text-faint">
            <span className="font-display font-600 text-mute">{n.league.toUpperCase()}</span>
            <DemoStamp />
          </div>
          <h3 className="mt-2 font-display text-xl font-600 leading-snug text-ink">{n.title}</h3>
          <p className="mt-2 text-[0.95rem] leading-relaxed text-mute">{n.body}</p>
        </li>
      ))}
    </ul>
  );
}
