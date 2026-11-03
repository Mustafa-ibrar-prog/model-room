"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { simulateSubscription } from "@/server/actions/test-subscription";

const BUTTONS = [
  { id: "plus", label: "Switch to Plus" },
  { id: "pro", label: "Switch to Pro" },
  { id: "free", label: "Downgrade to Free" },
  { id: "cancel", label: "Cancel (ends in 7 days)" },
  { id: "expire", label: "Expire now" },
] as const;

export function TestSubscriptionControls() {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {BUTTONS.map((b) => (
          <button
            key={b.id}
            type="button"
            disabled={pending}
            onClick={() =>
              start(async () => {
                const r = await simulateSubscription(b.id);
                setMsg(r.ok ? `Done. The server now sees: ${(r.tier ?? "free").replace(/^./, (c) => c.toUpperCase())}.` : (r.error ?? "That didn't work."));
                router.refresh();
              })
            }
            className="rounded-full border border-navy-600 px-3 py-1.5 text-sm text-ink hover:border-model disabled:opacity-60"
          >
            {b.label}
          </button>
        ))}
      </div>
      {msg ? <p role="status" data-testid="test-controls-status" className="mt-2 text-sm text-mute">{msg}</p> : null}
    </div>
  );
}
