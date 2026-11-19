"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV } from "./nav";

/**
 * Phone navigation: always visible, no menu to open. Replaces the hamburger drawer's nav list
 * (the drawer keeps the account panel, which is not navigation).
 */
const BALL = (
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M5 7c3 2 11 2 14 0M5 17c3-2 11-2 14 0M12 3v18" />
  </>
);
const FOOTBALL = (
  <>
    <ellipse cx="12" cy="12" rx="9" ry="6" />
    <path d="M8 12h8M10 10v4M14 10v4" />
  </>
);
const PERSON = (
  <>
    <circle cx="12" cy="8" r="3.5" />
    <path d="M5 20c1-4 4-6 7-6s6 2 7 6" />
  </>
);
const ICON: Record<string, React.ReactNode> = {
  "/nba-props": PERSON,
  "/nfl-props": PERSON,
  "/nba": BALL,
  "/nfl": FOOTBALL,
  "/pick-of-the-day": <path d="M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6.1L12 16.6 6.6 19.6l1.2-6.1L3.3 9.3l6.1-.7z" />,
  "/performance": <path d="M4 19V9M10 19V5M16 19v-7M22 19H2" />,
};
/** Phones: the four sports sections and Performance. The logo is the way home. */
const TABS = NAV.filter((n) => n.href !== "/");

export function MobileTabs() {
  const pathname = usePathname();
  const active = (href: string) => (href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`));

  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-navy-700 bg-navy-900/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
    >
      <ul className="flex">
        {TABS.map((item) => {
          const on = active(item.href);
          return (
            <li key={item.href} className="flex-1">
              <Link
                href={item.href}
                aria-current={on ? "page" : undefined}
                className={`flex min-h-14 flex-col items-center justify-center gap-1 py-2 text-[0.66rem] font-500 leading-none ${on ? "text-ink" : "text-mute"}`}
              >
                <svg viewBox="0 0 24 24" className="h-[22px] w-[22px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  {ICON[item.href]}
                </svg>
                {item.href === "/pick-of-the-day" ? "Pick" : item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
