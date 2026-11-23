/**
 * TEST-site sign-in diagnostics (Moose, 2026-11-23). On non-production deployments a failed sign-in shows Supabase's
 * error code, HTTP status and error class, plus whether the server is talking to the TEST project, so a key, project,
 * rate-limit or network problem can't hide behind "Email or password is incorrect." Production keeps the generic
 * message only.
 *
 * Never included anywhere: the password, any key, the Supabase URL, tokens, or Supabase's free-text message. The code
 * and class are allowlisted shapes; the project is reported as a yes/no match, and only server logs see the first four
 * characters of the project reference.
 */
import { createHash } from "node:crypto";

export const GENERIC_SIGNIN_ERROR = "Email or password is incorrect.";
export const UNCONFIRMED_ERROR = "Confirm your email first: check your inbox for the link.";

/** sha256 of the TEST project reference, first 8 hex characters (the same fingerprint the Supabase checks print). */
export const TEST_PROJECT_FP = "680cbd6c";

export type SigninError = { code?: unknown; status?: unknown; name?: unknown; message?: unknown };

const CODE = /^[a-z][a-z0-9_]{1,63}$/;
const NAME = /^Auth[A-Za-z]{1,40}Error$/;

/** Project reference from a Supabase URL (https://<ref>.supabase.co), or null. */
export function projectRef(url: string | null | undefined): string | null {
  const m = /^https:\/\/([a-z0-9]{20})\.supabase\.co\/?$/.exec(url ?? "");
  return m ? m[1] : null;
}

export function refFingerprint(ref: string): string {
  return createHash("sha256").update(ref).digest("hex").slice(0, 8);
}

/** Safe fields only: allowlisted code and class, numeric status, TEST-project match. */
export function diagFields(error: SigninError, ref: string | null) {
  const code = typeof error.code === "string" && CODE.test(error.code) ? error.code : null;
  const status = typeof error.status === "number" && Number.isInteger(error.status) && error.status >= 0 && error.status < 600 ? error.status : null;
  const name = typeof error.name === "string" && NAME.test(error.name) ? error.name : "other error";
  const testProject = ref ? refFingerprint(ref) === TEST_PROJECT_FP : null;
  return { code, status, name, testProject };
}

/** The message a visitor sees after a failed sign-in. Production: unchanged generic text. */
export function signinErrorMessage(error: SigninError, opts: { production: boolean; ref: string | null }): string {
  if (error.message === "Email not confirmed") return UNCONFIRMED_ERROR;
  if (opts.production) return GENERIC_SIGNIN_ERROR;
  const d = diagFields(error, opts.ref);
  const project = d.testProject === null ? "project unknown" : d.testProject ? "TEST project: yes" : "TEST project: NO";
  return `${GENERIC_SIGNIN_ERROR} (TEST diagnostics: code ${d.code ?? "none"}, HTTP ${d.status ?? "none"}, ${d.name}, ${project})`;
}

/** Server-log line (non-production only): same safe fields plus the first four characters of the project reference. */
export function signinLogLine(error: SigninError, ref: string | null): string {
  const d = diagFields(error, ref);
  return `[auth] sign-in failed: code=${d.code ?? "none"} status=${d.status ?? "none"} class=${d.name} project=${ref ? `${ref.slice(0, 4)}…` : "unknown"} test_project=${d.testProject ?? "unknown"}`;
}
