"use client";

import { useEffect, useRef } from "react";

/** Submits the surrounding filter form when a select changes (the Apply button still works without JS). */
export function AutoSubmit() {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const form = ref.current?.closest("form");
    if (!form) return;
    const onChange = (e: Event) => {
      if ((e.target as HTMLElement).tagName === "SELECT") form.requestSubmit();
    };
    form.addEventListener("change", onChange);
    return () => form.removeEventListener("change", onChange);
  }, []);
  return <span ref={ref} hidden />;
}
