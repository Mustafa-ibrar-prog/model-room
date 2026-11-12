import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { PageHeader, TableSkeleton } from "@/components/ui/primitives";
import { Legend } from "@/components/owner/parts";
import { BooksSection, CalibrationSection, FreshnessSection, MovementSection, PropsSection, ShadowSection, VersionsSection, VsMarketSection } from "@/components/owner/sections";
import { requireOwner } from "@/server/owner/access";
import { loadOwnerFiles, loadSchedulerHealth, loadSportsbook, requestTime } from "@/server/owner/data";
import { ownerDbConfigured } from "@/server/owner/db";
import type { League } from "@/types/domain";

/**
 * Owner analytics (TEST only). Reached only through the request proxy's owner check (src/proxy.ts); this page and
 * every loader check again with requireOwner(). Server-rendered throughout: no client component, no API route,
 * nothing owner-only in any bundle or public JSON. Read-only: no action on this page writes anything.
 */
export const metadata: Metadata = { title: "Owner analytics", robots: { index: false, follow: false } };

const VIEWS = [
  { key: "movement", label: "Line movement", db: true },
  { key: "market", label: "Model vs market", db: true },
  { key: "props", label: "Prop performance", db: false },
  { key: "calibration", label: "Calibration", db: false },
  { key: "shadow", label: "Active vs shadow", db: false },
  { key: "versions", label: "Version history", db: false },
  { key: "freshness", label: "Freshness & scheduler", db: true },
  { key: "books", label: "Sportsbook detail", db: true },
] as const;
type ViewKey = (typeof VIEWS)[number]["key"];

type SP = Promise<Record<string, string | string[] | undefined>>;
const one = (v: string | string[] | undefined) => (typeof v === "string" ? v : undefined);

export default function OwnerPage({ searchParams }: { searchParams: SP }) {
  return (
    <>
      <PageHeader title="Owner analytics" intro="Private to the owner, test site only. Read-only: observed market data and Model Room estimates side by side, with every sample gate shown." />
      <Suspense fallback={<div className="mx-auto max-w-7xl px-4 sm:px-6"><TableSkeleton rows={10} /></div>}>
        <Body searchParams={searchParams} />
      </Suspense>
    </>
  );
}

async function Body({ searchParams }: { searchParams: SP }) {
  await requireOwner();
  const now = await requestTime();
  const sp = await searchParams;
  const view: ViewKey = (VIEWS.find((v) => v.key === one(sp.view))?.key ?? "movement") as ViewKey;
  const league: League = one(sp.lg) === "nfl" ? "nfl" : "nba";
  const href = (patch: { view?: string; lg?: string }) => `/owner?${new URLSearchParams({ view, lg: league, ...patch }).toString()}`;
  const needsDb = VIEWS.find((v) => v.key === view)!.db;
  const [files, sb, sched] = await Promise.all([
    loadOwnerFiles(league),
    needsDb ? loadSportsbook(league) : Promise.resolve({ ok: false as const, reason: "not_configured" as const }),
    view === "freshness" ? loadSchedulerHealth() : Promise.resolve({ ok: false as const, reason: "not_configured" as const }),
  ]);
  return (
    <div className="mx-auto max-w-7xl space-y-5 px-4 pb-16 sm:px-6">
      <div className="flex flex-wrap items-center gap-3">
        <nav aria-label="League" className="flex gap-0.5 rounded-full bg-navy-850 p-0.5">
          {(["nba", "nfl"] as const).map((l) => (
            <Link key={l} href={href({ lg: l })} aria-current={l === league ? "page" : undefined} prefetch={false}
              className={`rounded-full px-3.5 py-1.5 text-sm font-600 ${l === league ? "bg-model text-navy-950" : "text-mute hover:text-ink"}`}>{l.toUpperCase()}</Link>
          ))}
        </nav>
        <span className={`text-xs ${ownerDbConfigured() ? "text-mute" : "text-edge"}`}>
          Read-only database: {ownerDbConfigured() ? "configured" : "not configured (sections that need it show as unavailable)"}
        </span>
      </div>
      <nav aria-label="Dashboard sections" className="-mx-4 flex gap-1 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0">
        {VIEWS.map((v, i) => (
          <Link key={v.key} href={href({ view: v.key })} aria-current={v.key === view ? "page" : undefined} prefetch={false}
            className={`shrink-0 whitespace-nowrap rounded-full px-3 py-1.5 text-sm ${v.key === view ? "bg-ink font-500 text-navy-950" : "bg-navy-850 text-mute hover:text-ink"}`}>
            {i + 1}. {v.label}
          </Link>
        ))}
      </nav>
      <Legend />
      <h2 className="font-display text-2xl font-700 text-ink">{VIEWS.findIndex((v) => v.key === view) + 1}. {VIEWS.find((v) => v.key === view)!.label} · {league.toUpperCase()}</h2>
      {view === "movement" ? <MovementSection sb={sb} league={league} /> : null}
      {view === "market" ? <VsMarketSection sb={sb} league={league} /> : null}
      {view === "props" ? <PropsSection files={files} league={league} /> : null}
      {view === "calibration" ? <CalibrationSection files={files} league={league} /> : null}
      {view === "shadow" ? <ShadowSection files={files} league={league} /> : null}
      {view === "versions" ? <VersionsSection files={files} league={league} /> : null}
      {view === "freshness" ? <FreshnessSection files={files} sched={sched} sb={sb} now={now} league={league} /> : null}
      {view === "books" ? <BooksSection sb={sb} league={league} /> : null}
    </div>
  );
}
