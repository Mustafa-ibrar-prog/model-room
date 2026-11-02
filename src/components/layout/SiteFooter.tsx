import Link from "next/link";
import { Suspense } from "react";
import { Wordmark } from "./Logo";
import { NAV } from "./nav";
import { TierPreview } from "@/components/dev/TierPreview";

export function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-navy-700/70 bg-navy-900/60">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-12 sm:px-6 md:grid-cols-[1.4fr_1fr_1fr]">
        <div className="max-w-sm">
          <Wordmark />
          <p className="mt-4 text-sm leading-relaxed text-mute">
            NFL and NBA projections compared against the market. For information and entertainment.
            Model Room does not accept wagers.
          </p>
          <p className="mt-3 text-sm leading-relaxed text-mute">
            If gambling stops being fun, call or text 1-800-GAMBLER.
          </p>
        </div>
        <nav aria-label="Boards">
          <h2 className="font-display text-base font-600 text-ink">Boards</h2>
          <ul className="mt-3 space-y-2 text-sm">
            {NAV.map((item) => (
              <li key={item.href}>
                <Link href={item.href} className="text-mute hover:text-ink">
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <nav aria-label="Model Room">
          <h2 className="font-display text-base font-600 text-ink">Model Room</h2>
          <ul className="mt-3 space-y-2 text-sm">
            <li><Link href="/#how-it-works" className="text-mute hover:text-ink">How it works</Link></li>
            <li><Link href="/#data-sources" className="text-mute hover:text-ink">Data sources</Link></li>
            <li><Link href="/pricing" className="text-mute hover:text-ink">Pricing</Link></li>
          </ul>
        </nav>
      </div>
      <Suspense fallback={null}>
        <TierPreview />
      </Suspense>
    </footer>
  );
}
