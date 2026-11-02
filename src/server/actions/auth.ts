"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { authEnabled, isProduction, isTestAccount, safeNext } from "@/lib/auth-config";
import { createSupabaseServerClient } from "@/lib/supabase/server";

export type AuthState = { error?: string; message?: string } | undefined;

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

async function siteOrigin(): Promise<string> {
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host");
  const proto = h.get("x-forwarded-proto") ?? "https";
  return process.env.APP_URL ?? `${proto}://${host}`;
}

function field(form: FormData, name: string): string {
  const v = form.get(name);
  return typeof v === "string" ? v.trim() : "";
}

async function client() {
  if (!authEnabled()) return null;
  return createSupabaseServerClient();
}

export async function signIn(_: AuthState, form: FormData): Promise<AuthState> {
  const email = field(form, "email").toLowerCase();
  const password = typeof form.get("password") === "string" ? (form.get("password") as string) : "";
  const next = safeNext(field(form, "next"), "/account");
  if (!EMAIL.test(email) || !password) return { error: "Enter your email and password." };
  if (isProduction() && isTestAccount(email)) return { error: "Test accounts only work on the test site." };
  const supabase = await client();
  if (!supabase) return { error: "Sign-in isn't set up on this site yet." };
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) return { error: error.message === "Email not confirmed" ? "Confirm your email first: check your inbox for the link." : "Email or password is incorrect." };
  redirect(next);
}

export async function signUp(_: AuthState, form: FormData): Promise<AuthState> {
  const email = field(form, "email").toLowerCase();
  const password = typeof form.get("password") === "string" ? (form.get("password") as string) : "";
  const next = safeNext(field(form, "next"), "/account");
  if (!EMAIL.test(email)) return { error: "Enter a valid email address." };
  if (password.length < 8) return { error: "Use at least 8 characters for your password." };
  if (isTestAccount(email)) return { error: "That address is reserved for test accounts." };
  const supabase = await client();
  if (!supabase) return { error: "Sign-up isn't set up on this site yet." };
  const origin = await siteOrigin();
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: { emailRedirectTo: `${origin}/auth/callback?next=${encodeURIComponent(next)}` },
  });
  if (error) return { error: error.message };
  if (data.session) redirect(next);
  return { message: "Check your email for a link to confirm your account." };
}

export async function signOut(): Promise<void> {
  const supabase = await client();
  if (supabase) await supabase.auth.signOut();
  redirect("/");
}

export async function requestPasswordReset(_: AuthState, form: FormData): Promise<AuthState> {
  const email = field(form, "email").toLowerCase();
  if (!EMAIL.test(email)) return { error: "Enter a valid email address." };
  const supabase = await client();
  if (!supabase) return { error: "Password reset isn't set up on this site yet." };
  const origin = await siteOrigin();
  await supabase.auth.resetPasswordForEmail(email, { redirectTo: `${origin}/auth/callback?next=/reset-password` });
  // Same answer whether or not the address has an account, so the form can't be used to find accounts.
  return { message: "If that address has an account, a reset link is on its way." };
}

export async function updatePassword(_: AuthState, form: FormData): Promise<AuthState> {
  const password = typeof form.get("password") === "string" ? (form.get("password") as string) : "";
  if (password.length < 8) return { error: "Use at least 8 characters." };
  const supabase = await client();
  if (!supabase) return { error: "Sign-in isn't set up on this site yet." };
  const { data } = await supabase.auth.getUser();
  if (!data.user) return { error: "Your reset link has expired. Request a new one." };
  const { error } = await supabase.auth.updateUser({ password });
  if (error) return { error: error.message };
  redirect("/account?updated=1");
}
