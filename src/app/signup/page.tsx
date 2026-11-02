import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthForm } from "@/components/auth/AuthForm";
import { AuthShell } from "@/components/auth/AuthShell";
import { safeNext } from "@/lib/auth-config";
import { signUp } from "@/server/actions/auth";

export const metadata: Metadata = { title: "Create account" };

export default function SignupPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  return (
    <Suspense fallback={null}>
      <Signup searchParams={searchParams} />
    </Suspense>
  );
}

async function Signup({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const next = safeNext((await searchParams).next, "/account");
  return (
    <AuthShell title="Create an account" intro="An account is needed for Plus and Pro. Free features work without one.">
      <AuthForm
        action={signUp}
        next={next}
        submit="Create account"
        fields={[
          { name: "email", label: "Email", type: "email", autoComplete: "email" },
          { name: "password", label: "Password (8+ characters)", type: "password", autoComplete: "new-password" },
        ]}
        footer={[{ text: "Already have an account?", href: `/login?next=${encodeURIComponent(next)}`, link: "Sign in" }]}
      />
    </AuthShell>
  );
}
