import type { ReactNode } from "react";
import { authEnabled } from "@/lib/auth-config";
import { Panel } from "@/components/ui/primitives";

export function AuthShell({ title, intro, children }: { title: string; intro?: string; children: ReactNode }) {
  return (
    <div className="mx-auto max-w-md px-4 py-14 sm:px-6">
      <h1 className="font-display text-4xl font-700 text-ink">{title}</h1>
      {intro ? <p className="mt-2 text-mute">{intro}</p> : null}
      <Panel className="mt-6 p-6">
        {authEnabled() ? children : <p className="text-sm text-mute">Accounts aren&apos;t switched on for this site yet.</p>}
      </Panel>
    </div>
  );
}
