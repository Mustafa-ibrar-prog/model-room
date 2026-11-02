"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import type { TierId } from "@/types/domain";

/** Link to the sign-in / upgrade prompt that remembers where the visitor was (path and filters). */
export function UpgradeLink({ requires, className, title, children }: { requires: TierId; className?: string; title?: string; children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const base = `/upgrade?requires=${requires}&next=`;
  return (
    <Link
      href={base + encodeURIComponent(pathname)}
      className={className}
      title={title}
      onClick={(e) => {
        e.preventDefault();
        router.push(base + encodeURIComponent(window.location.pathname + window.location.search));
      }}
    >
      {children}
    </Link>
  );
}
