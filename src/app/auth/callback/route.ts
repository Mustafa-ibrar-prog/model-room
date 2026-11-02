import { NextResponse, type NextRequest } from "next/server";
import { safeNext } from "@/lib/auth-config";
import { createSupabaseServerClient } from "@/lib/supabase/server";

/** Email links (confirm sign-up, reset password) land here with a one-time code. */
export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get("code");
  const next = safeNext(request.nextUrl.searchParams.get("next"), "/account");
  const supabase = await createSupabaseServerClient();
  if (code && supabase) {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) return NextResponse.redirect(new URL(next, request.url));
  }
  return NextResponse.redirect(new URL("/login?error=link", request.url));
}
