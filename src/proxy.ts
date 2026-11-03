import { createServerClient } from "@supabase/ssr";
import { publicSupabaseKey, supabaseUrl } from "@/lib/supabase/keys";
import { NextResponse, type NextRequest } from "next/server";

/**
 * Keeps the Supabase login fresh: refreshes the access token cookie when it's near expiry.
 * Does nothing when logins aren't configured. Access decisions are made on the server per request
 * (src/server/viewer.ts), never here.
 */
export async function proxy(request: NextRequest) {
  const url = supabaseUrl();
  const key = publicSupabaseKey();
  let response = NextResponse.next({ request });
  if (!url || !key) return response;
  const supabase = createServerClient(url, key, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (list) => {
        list.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        list.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });
  await supabase.auth.getUser();
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|woff2?)$).*)"],
};
