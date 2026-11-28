import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { connection } from "next/server";
import { isProduction } from "@/lib/auth-config";
import { ParlayBuilder } from "@/components/parlay/Builder";
import { TableSkeleton } from "@/components/ui/primitives";
import { geminiEnabled, GEMINI_MODEL } from "@/server/ai/gemini";
import { limits } from "@/server/ai/limits";
import { getCatalog } from "@/server/parlay/legs";
import { loadValidation } from "@/server/parlay/validation";
import { liveMarketsOn } from "@/server/markets/polymarketLive";

export const metadata: Metadata = { title: "Parlay Builder" };

/** Parlay Builder (TEST only, Moose 2026-11-27): combine NBA and NFL legs, see the model's joint probability. */
export default function ParlayPage() {
  if (isProduction()) notFound();
  return (
    <div className="mx-auto w-full max-w-7xl px-4 pb-16 pt-6 sm:px-6">
      <p className="mb-1 text-sm font-600 text-model">Parlay Builder</p>
      <h1 className="font-display text-3xl font-700 leading-none tracking-tight text-ink sm:text-4xl">Build a parlay. See what it&apos;s really worth.</h1>
      <p className="mt-2 max-w-2xl text-[0.95rem] leading-relaxed text-mute">
        Pick legs from any game. The model prices each one, then measures how they move together using years of box scores.
      </p>
      <Suspense fallback={<div className="mt-6"><TableSkeleton rows={6} /></div>}>
        <Loaded />
      </Suspense>
    </div>
  );
}

async function Loaded() {
  await connection();
  const priv = liveMarketsOn();
  const [nba, nfl] = await Promise.all([getCatalog("nba", new Date(), { live: priv }), getCatalog("nfl", new Date(), { live: priv })]);
  const pmNote = priv
    ? [nba, nfl].filter((c) => c.pm).map((c) => `${c.league.toUpperCase()}: ${c.pm!.eventsFound}/${c.pm!.games} games found, ${c.pm!.legsWithQuote} legs priced.`).join(" ")
    : null;
  return (
    <ParlayBuilder
      games={{ nba: nba.games, nfl: nfl.games }}
      asOf={[...nba.asOf, ...nfl.asOf]}
      validation={loadValidation()}
      ai={{ enabled: geminiEnabled(), model: GEMINI_MODEL, perDay: limits().user }}
      live={{ on: priv, pm: pmNote }}
    />
  );
}
