import type { Metadata, Viewport } from "next";
import "@fontsource/barlow-condensed/500.css";
import "@fontsource/barlow-condensed/600.css";
import "@fontsource/barlow-condensed/700.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./globals.css";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { AccountMenu } from "@/components/auth/AccountMenu";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { Suspense } from "react";
import { DataStatus, DataStatusFallback } from "@/components/layout/DataStatus";

export const metadata: Metadata = {
  title: { default: "Model Room — NFL and NBA projections", template: "%s · Model Room" },
  description:
    "Model Room compares NFL and NBA market lines with model projections for spreads, totals, player props and injury impact.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f3f5f8" },
    { media: "(prefers-color-scheme: dark)", color: "#0e151d" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full">
      <body className="flex min-h-full flex-col">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-model focus:px-3 focus:py-2 focus:text-navy-950"
        >
          Skip to content
        </a>
        {process.env.VERCEL_ENV === "preview" ? (
          <div className="bg-edge/15 px-4 py-1.5 text-center text-xs text-edge">
            Test site: features are still being built and numbers are provisional.
          </div>
        ) : null}
        <SiteHeader
          account={
            <Suspense fallback={null}>
              <AccountMenu variant="desktop" />
            </Suspense>
          }
          mobileAccount={
            <Suspense fallback={null}>
              <AccountMenu variant="mobile" />
            </Suspense>
          }
        />
        <Suspense fallback={<DataStatusFallback />}>
          <DataStatus />
        </Suspense>
        <main id="main" className="flex-1">
          {children}
        </main>
        <SiteFooter />
      </body>
    </html>
  );
}
