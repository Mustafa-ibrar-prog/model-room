import type { ReactNode } from "react";
import { authEnabled, isProduction } from "@/lib/auth-config";
import { supabaseConfigReport } from "@/lib/supabase/keys";
import { Panel } from "@/components/ui/primitives";

/** Shared frame for sign-in pages. On the test site, if logins are off, it says which setting is missing (names only, never values). */
export function AuthShell({ title, intro, children }: { title: string; intro?: string; children: ReactNode }) {
  const on = authEnabled();
  const report = !on && !isProduction() ? supabaseConfigReport() : null;
  return (
    <div className="mx-auto max-w-md px-4 py-14 sm:px-6">
      <h1 className="font-display text-4xl font-700 text-ink">{title}</h1>
      {intro ? <p className="mt-2 text-mute">{intro}</p> : null}
      <Panel className="mt-6 p-6">
        {on ? (
          children
        ) : report ? (
          <div className="space-y-3 text-sm">
            <p className="text-ink">Logins aren&apos;t connected on this deployment yet.</p>
            <ul className="list-disc space-y-1 pl-5 font-mono text-xs text-mute">
              {report.lines.map((l) => <li key={l}>{l}</li>)}
            </ul>
            <p className="text-xs text-faint">
              Set these in Vercel → Settings → Environment Variables for Preview, then redeploy. Only setting names and key types are shown here, never values.
            </p>
          </div>
        ) : (
          <p className="text-sm text-mute">Accounts aren&apos;t switched on for this site yet.</p>
        )}
      </Panel>
    </div>
  );
}
