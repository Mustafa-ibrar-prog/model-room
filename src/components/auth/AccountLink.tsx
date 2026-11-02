import Link from "next/link";
import { authEnabled } from "@/lib/auth-config";
import { getSessionUser } from "@/server/session";

/** Header link: "Sign in" for guests, "Account" when signed in. Nothing when logins aren't configured. */
export async function AccountLink({ className = "" }: { className?: string }) {
  if (!authEnabled()) return null;
  const user = await getSessionUser();
  return (
    <Link href={user ? "/account" : "/login"} className={className}>
      {user ? "Account" : "Sign in"}
    </Link>
  );
}
