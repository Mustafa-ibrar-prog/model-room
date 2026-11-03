import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthForm } from "@/components/auth/AuthForm";
import { AuthShell } from "@/components/auth/AuthShell";
import { safeNext } from "@/lib/auth-config";
import { signIn } from "@/server/actions/auth";

export const metadata: Metadata = { title: "Log in" };

const REQUIRES: Record<string, string> = { plus: "Plus", pro: "Pro" };

export default function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string; requires?: string; error?: string }> }) {
  return (
    <Suspense fallback={null}>
      <Login searchParams={searchParams} />
    </Suspense>
  );
}

async function Login({ searchParams }: { searchParams: Promise<{ next?: string; requires?: string; error?: string }> }) {
  const sp = await searchParams;
  const next = safeNext(sp.next, "/account");
  const plan = sp.requires ? REQUIRES[sp.requires] : null;
  const intro = sp.error === "link"
    ? "That link has expired or was already used. Sign in, or request a new one."
    : plan
      ? `That's part of ${plan}. Sign in to an account with ${plan}, and you'll go straight back to it.`
      : "Free features don't need an account.";
  return (
    <AuthShell title="Log in" intro={intro}>
      <AuthForm
        action={signIn}
        next={next}
        submit="Log in"
        fields={[
          { name: "email", label: "Email", type: "email", autoComplete: "email" },
          { name: "password", label: "Password", type: "password", autoComplete: "current-password" },
        ]}
        footer={[
          { text: "New here?", href: `/signup?next=${encodeURIComponent(next)}`, link: "Create an account" },
          { text: "Forgot your password?", href: "/forgot-password", link: "Reset it" },
        ]}
      />
    </AuthShell>
  );
}
