import type { Metadata } from "next";
import { AuthForm } from "@/components/auth/AuthForm";
import { AuthShell } from "@/components/auth/AuthShell";
import { updatePassword } from "@/server/actions/auth";

export const metadata: Metadata = { title: "Choose a new password" };

export default function ResetPasswordPage() {
  return (
    <AuthShell title="Choose a new password">
      <AuthForm
        action={updatePassword}
        submit="Save password"
        fields={[{ name: "password", label: "New password (8+ characters)", type: "password", autoComplete: "new-password" }]}
      />
    </AuthShell>
  );
}
