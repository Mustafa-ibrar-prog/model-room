import type { Metadata } from "next";
import { AuthForm } from "@/components/auth/AuthForm";
import { AuthShell } from "@/components/auth/AuthShell";
import { requestPasswordReset } from "@/server/actions/auth";

export const metadata: Metadata = { title: "Reset password" };

export default function ForgotPasswordPage() {
  return (
    <AuthShell title="Reset your password" intro="We'll email you a link to choose a new one.">
      <AuthForm
        action={requestPasswordReset}
        submit="Send reset link"
        fields={[{ name: "email", label: "Email", type: "email", autoComplete: "email" }]}
        footer={[{ text: "Remembered it?", href: "/login", link: "Sign in" }]}
      />
    </AuthShell>
  );
}
