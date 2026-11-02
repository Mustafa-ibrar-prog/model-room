import type { Metadata, Viewport } from "next";
import "@fontsource/barlow/400.css";
import "@fontsource/barlow/500.css";
import "@fontsource/barlow/600.css";
import "@fontsource/barlow-condensed/500.css";
import "@fontsource/barlow-condensed/600.css";
import "@fontsource/barlow-condensed/700.css";
import "./globals.css";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { Suspense } from "react";
import { DataStatus, DataStatusFallback } from "@/components/layout/DataStatus";

export const metadata: Metadata = {
  title: { default: "Model Room — NFL and NBA projections", template: "%s · Model Room" },
  description:
    "Model Room compares NFL and NBA market lines with model projections for spreads, totals, player props and injury impact.",
};

export const viewport: Viewport = {
  themeColor: "#061020",
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
        <SiteHeader />
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
