import { createServerClient } from "@supabase/ssr";
import { publicSupabaseKey, supabaseUrl } from "@/lib/supabase/keys";
import { NextResponse, type NextRequest } from "next/server";
import { devSessionEmail, isOwnerEmail, isOwnerPath, ownerConfig } from "@/server/owner/policy";

/**
 * Keeps the Supabase login fresh: refreshes the access token cookie when it's near expiry.
 * Does nothing when logins aren't configured. Subscription access decisions are made on the server per request
 * (src/server/viewer.ts), never here.
 *
 * One exception: the owner dashboard (/owner) is refused HERE, before anything renders, for everyone who is not
 * the owner (src/server/owner/policy.ts): they get the site's ordinary 404 page with a 404 status, so the route's
 * existence and its data are never sent. The page and every owner loader check again on the server.
 */
function notFoundResponse(request: NextRequest) {
  const res = NextResponse.rewrite(new URL("/__not-found", request.url), { status: 404 });
  res.headers.set("Cache-Control", "private, no-store");
  res.headers.set("X-Robots-Tag", "noindex, nofollow");
  return res;
}

function noStore(res: NextResponse) {
  res.headers.set("Cache-Control", "private, no-store");
  res.headers.set("X-Robots-Tag", "noindex, nofollow");
  return res;
}

export async function proxy(request: NextRequest) {
  const url = supabaseUrl();
  const key = publicSupabaseKey();
  const owner = isOwnerPath(request.nextUrl.pathname);
  if (owner && !ownerConfig().ok) return notFoundResponse(request);
  let response = NextResponse.next({ request });
  if (!url || !key) {
    if (!owner) return response;
    return isOwnerEmail(devSessionEmail()) ? noStore(response) : notFoundResponse(request);
  }
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
  const { data } = await supabase.auth.getUser();
  if (owner) return isOwnerEmail(data.user?.email ?? devSessionEmail()) ? noStore(response) : notFoundResponse(request);
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|woff2?)$).*)"],
};
