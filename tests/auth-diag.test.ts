import { describe, expect, it } from "vitest";
import { diagFields, GENERIC_SIGNIN_ERROR, projectRef, refFingerprint, signinErrorMessage, signinLogLine, TEST_PROJECT_FP, UNCONFIRMED_ERROR } from "@/lib/auth-diag";

const REF = "abcdefghijklmnopqrst";                       // made-up 20-character project reference
const URL = `https://${REF}.supabase.co`;
const SECRET_PW = "hunter2-correct-horse";
const SECRET_KEY = "sb_secret_ZZZZZZZZZZZZZZZZ";
const bad = { code: "invalid_credentials", status: 400, name: "AuthApiError", message: "Invalid login credentials" };

describe("sign-in diagnostics", () => {
  it("production: the generic message, unchanged, whatever Supabase returned", () => {
    for (const e of [bad, { status: 401, name: "AuthApiError", message: "Invalid API key" }, { status: 0, name: "AuthRetryableFetchError", message: "fetch failed" }, { code: "over_request_rate_limit", status: 429, name: "AuthApiError" }]) {
      expect(signinErrorMessage(e, { production: true, ref: projectRef(URL) })).toBe(GENERIC_SIGNIN_ERROR);
      expect(signinErrorMessage(e, { production: true, ref: null })).toBe("Email or password is incorrect.");
    }
  });

  it("unconfirmed email keeps its own message in both environments", () => {
    const e = { code: "email_not_confirmed", status: 400, name: "AuthApiError", message: "Email not confirmed" };
    expect(signinErrorMessage(e, { production: true, ref: null })).toBe(UNCONFIRMED_ERROR);
    expect(signinErrorMessage(e, { production: false, ref: null })).toBe(UNCONFIRMED_ERROR);
  });

  it("TEST: shows the code, HTTP status, error class and whether this is the TEST project", () => {
    expect(signinErrorMessage(bad, { production: false, ref: REF })).toBe(`${GENERIC_SIGNIN_ERROR} (TEST diagnostics: code invalid_credentials, HTTP 400, AuthApiError, TEST project: NO)`);
    expect(signinErrorMessage({ code: "over_request_rate_limit", status: 429, name: "AuthApiError" }, { production: false, ref: null })).toContain("code over_request_rate_limit, HTTP 429, AuthApiError, project unknown");
    expect(signinErrorMessage({ status: 0, name: "AuthRetryableFetchError", message: "fetch failed" }, { production: false, ref: null })).toContain("code none, HTTP 0, AuthRetryableFetchError");
    expect(signinErrorMessage({ status: 401, name: "AuthApiError", message: "Invalid API key" }, { production: false, ref: null })).toContain("code none, HTTP 401");
  });

  it("the TEST-project check compares fingerprints, never the reference itself", () => {
    expect(refFingerprint(REF)).toMatch(/^[0-9a-f]{8}$/);
    expect(diagFields(bad, REF).testProject).toBe(refFingerprint(REF) === TEST_PROJECT_FP);
    expect(diagFields(bad, null).testProject).toBeNull();
    expect(signinErrorMessage(bad, { production: false, ref: REF })).not.toContain(REF.slice(0, 4));
  });

  it("never shows passwords, keys, URLs, tokens or Supabase's free text, even if they arrive in the error", () => {
    const hostile = { code: `x ${SECRET_KEY}`, status: "400" as unknown, name: `<script>${SECRET_PW}`, message: `Invalid ${SECRET_PW} ${URL} ${SECRET_KEY}` };
    for (const s of [signinErrorMessage(hostile, { production: false, ref: REF }), signinLogLine(hostile, REF)]) {
      for (const leak of [SECRET_PW, SECRET_KEY, URL, REF, "supabase.co", "<script>"]) expect(s).not.toContain(leak);
      expect(s).toContain("none");
    }
    expect(diagFields({ code: "A_Upper", status: 999, name: "TypeError" }, null)).toEqual({ code: null, status: null, name: "other error", testProject: null, reason: null });
  });

  it("HTTP 402 shows Supabase's restriction reason token only, never the surrounding text", () => {
    const e = { status: 402, name: "AuthApiError", message: `Service for this project is restricted due to the following violations: exceed_db_size_quota. ${SECRET_KEY}` };
    const m = signinErrorMessage(e, { production: false, ref: null });
    expect(m).toContain("HTTP 402 (service restricted: exceed_db_size_quota)");
    expect(m).not.toContain(SECRET_KEY);
    expect(m).not.toContain("violations");
    expect(signinErrorMessage({ status: 402, name: "AuthApiError", message: "overdue_payment" }, { production: false, ref: null })).toContain("service restricted: overdue_payment");
    expect(signinErrorMessage(e, { production: true, ref: null })).toBe(GENERIC_SIGNIN_ERROR);
    expect(diagFields({ status: 400, message: "exceed_db_size_quota" }, null).reason).toBeNull();     // only with 402
  });

  it("server log line carries only the first four characters of the project reference", () => {
    const line = signinLogLine(bad, REF);
    expect(line).toBe(`[auth] sign-in failed: code=invalid_credentials status=400 class=AuthApiError project=abcd… test_project=${refFingerprint(REF) === TEST_PROJECT_FP}`);
    expect(line).not.toContain(REF);
    expect(projectRef("https://evil.example.com")).toBeNull();
    expect(projectRef(URL)).toBe(REF);
  });
});
