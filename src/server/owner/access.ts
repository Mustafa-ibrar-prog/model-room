import "server-only";
import { notFound } from "next/navigation";
import { getSessionUser } from "@/server/session";
import { devSessionEmail, isOwnerEmail } from "./policy";

/**
 * Second gate behind the request proxy: every owner page and every owner data loader calls this first.
 * Anyone but the owner gets the not-found page; nothing owner-only is read before this returns.
 */
export async function requireOwner(): Promise<{ email: string }> {
  const email = (await getSessionUser())?.email ?? devSessionEmail();
  if (!email || !isOwnerEmail(email)) notFound();
  return { email };
}
