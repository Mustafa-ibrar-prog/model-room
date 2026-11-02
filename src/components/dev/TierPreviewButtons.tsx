"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { setPreviewTier } from "@/server/actions/preview-tier";
import type { TierId } from "@/types/domain";

const TIERS: { id: TierId; label: string }[] = [
  { id: "free", label: "Free" },
  { id: "plus", label: "Plus" },
  { id: "pro", label: "Pro" },
];

export function TierPreviewButtons({ current }: { current: TierId }) {
  const router = useRouter();
  const [pending, start] = useTransition();

  return (
    <div role="group" aria-label="Preview plan" className="flex rounded-full border border-navy-700 p-0.5">
      {TIERS.map((t) => (
        <button
          key={t.id}
          type="button"
          disabled={pending}
          aria-pressed={current === t.id}
          onClick={() =>
            start(async () => {
              await setPreviewTier(t.id);
              router.refresh();
            })
          }
          className={`rounded-full px-3 py-1 font-500 ${
            current === t.id ? "bg-navy-700 text-ink" : "text-mute hover:text-ink"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
