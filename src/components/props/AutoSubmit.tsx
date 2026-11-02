"use client";

import { useEffect, useRef } from "react";

/** Submits the surrounding filter form when a select changes (the Apply button still works without JS). */
export function AutoSubmit({ inputs = false }: { inputs?: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const form = ref.current?.closest("form");
    if (!form) return;
    const onChange = (e: Event) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "SELECT" || (inputs && tag === "INPUT" && (e.target as HTMLInputElement).type === "date")) form.requestSubmit();
    };
    form.addEventListener("change", onChange);
    return () => form.removeEventListener("change", onChange);
  }, [inputs]);
  return <span ref={ref} hidden />;
}
