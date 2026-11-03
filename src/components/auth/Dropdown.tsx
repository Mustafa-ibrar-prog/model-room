"use client";

import { useEffect, useRef, type ReactNode } from "react";

/** A <details> menu that also closes on an outside click, Escape, or choosing an item. Works without JS. */
export function Dropdown({ summary, label, children }: { summary: ReactNode; label: string; children: ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const close = (e: Event) => {
      if (!el.open) return;
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !el.contains(e.target as Node)) el.open = false;
    };
    document.addEventListener("click", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("click", close);
      document.removeEventListener("keydown", close);
    };
  }, []);
  return (
    <details ref={ref} className="relative">
      <summary aria-label={label} className="flex cursor-pointer list-none items-center gap-2 rounded-full border border-navy-700 py-1 pl-1 pr-3 hover:border-navy-600 [&::-webkit-details-marker]:hidden">
        {summary}
      </summary>
      <div className="absolute right-0 z-50 mt-2 w-64 rounded-lg border border-navy-700 bg-navy-900 p-2 shadow-lg" onClick={() => ref.current && (ref.current.open = false)}>
        {children}
      </div>
    </details>
  );
}
