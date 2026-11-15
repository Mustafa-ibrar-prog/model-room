"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { Wordmark } from "./Logo";
import { NAV } from "./nav";

export function SiteHeader({ account, mobileAccount }: { account?: ReactNode; mobileAccount?: ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  return (
    <header className="sticky top-0 z-40 border-b border-navy-700/70 bg-navy-950/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-6 px-4 sm:px-6">
        <Link href="/" className="shrink-0" aria-label="Model Room home" onClick={() => setOpen(false)}>
          <Wordmark />
        </Link>

        <nav aria-label="Main" className="hidden flex-1 lg:block">
          <ul className="flex items-center gap-1">
            {NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={isActive(item.href) ? "page" : undefined}
                  className={`rounded-md px-2.5 py-2 font-display text-[1rem] font-600 tracking-wide transition-colors ${
                    isActive(item.href) ? "bg-navy-800 text-model" : "text-mute hover:text-ink"
                  }`}
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        <div className="ml-auto hidden items-center gap-2 lg:flex">
          <Link
            href="/pricing"
            className="rounded-full bg-model px-4 py-2 text-sm font-600 text-navy-950 hover:bg-model/90"
          >
            See plans
          </Link>
          {account}
        </div>

        {/* Phones navigate from the bottom tabs, so this button is only the account area and plans. */}
        <button
          type="button"
          className="ml-auto rounded-full border border-navy-600 px-3.5 py-2 text-sm font-500 text-ink lg:hidden"
          aria-expanded={open}
          aria-controls="mobile-account"
          onClick={() => setOpen((v) => !v)}
        >
          Account
        </button>
      </div>

      {open && (
        <div id="mobile-account" className="border-t border-navy-700/70 lg:hidden" onClick={(e) => { if ((e.target as HTMLElement).closest("a")) setOpen(false); }}>
          <div className="mx-auto max-w-7xl space-y-3 px-4 py-3">
            {mobileAccount}
            <Link href="/pricing" onClick={() => setOpen(false)} className="block rounded-full bg-model px-4 py-2.5 text-center font-600 text-navy-950">
              See plans
            </Link>
          </div>
        </div>
      )}
    </header>
  );
}
