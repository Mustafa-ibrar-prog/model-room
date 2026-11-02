"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Wordmark } from "./Logo";
import { NAV } from "./nav";

export function SiteHeader() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  return (
    <header className="sticky top-0 z-40 border-b border-navy-700/70 bg-navy-950/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-6 px-4 sm:px-6">
        <Link href="/" className="shrink-0" aria-label="Model Room home" onClick={() => setOpen(false)}>
          <Wordmark />
        </Link>

        <nav aria-label="Main" className="hidden flex-1 md:block">
          <ul className="flex items-center gap-1">
            {NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={isActive(item.href) ? "page" : undefined}
                  className={`rounded-md px-3 py-2 font-display text-[1.05rem] font-600 tracking-wide transition-colors ${
                    isActive(item.href) ? "bg-navy-800 text-model" : "text-mute hover:text-ink"
                  }`}
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        <div className="ml-auto hidden items-center gap-3 md:flex">
          <Link
            href="/pricing"
            aria-current={isActive("/pricing") ? "page" : undefined}
            className="rounded-md px-3 py-2 text-sm font-500 text-mute hover:text-ink"
          >
            Pricing
          </Link>
          <Link
            href="/pricing"
            className="rounded-full bg-model px-4 py-2 text-sm font-600 text-navy-950 hover:bg-model/90"
          >
            See plans
          </Link>
        </div>

        <button
          type="button"
          className="ml-auto rounded-md p-2 text-ink md:hidden"
          aria-expanded={open}
          aria-controls="mobile-nav"
          onClick={() => setOpen((v) => !v)}
        >
          <span className="sr-only">{open ? "Close menu" : "Open menu"}</span>
          <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            {open ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
          </svg>
        </button>
      </div>

      {open && (
        <nav id="mobile-nav" aria-label="Main" className="border-t border-navy-700/70 md:hidden">
          <ul className="mx-auto grid max-w-7xl grid-cols-2 gap-1 px-4 py-3">
            {[...NAV, { href: "/pricing", label: "Pricing" }].map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  onClick={() => setOpen(false)}
                  aria-current={isActive(item.href) ? "page" : undefined}
                  className={`block rounded-md px-3 py-2.5 font-display text-lg font-600 ${
                    isActive(item.href) ? "bg-navy-800 text-model" : "text-ink"
                  }`}
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </header>
  );
}
