"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import type { TierId } from "@/types/domain";

/** Link to the sign-in / upgrade prompt that remembers where the visitor was. */
export function UpgradeLink({ requires, className, title, children }: { requires: TierId; className?: string; title?: string; children: ReactNode }) {
  const pathname = usePathname();
  const next = typeof window !== "undefined" ? pathname + window.location.search : pathname;
  return (
    <Link href={`/upgrade?requires=${requires}&next=${encodeURIComponent(next)}`} className={className} title={title}>
      {children}
    </Link>
  );
}
