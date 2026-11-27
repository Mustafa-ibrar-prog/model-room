import "server-only";
import { isProduction } from "@/lib/auth-config";

/**
 * Gemini, server side only (TEST, Moose 2026-11-27). Model gemini-3.5-flash-lite on Google's free tier.
 *   - The key comes from the GEMINI_API_KEY server environment variable; it is sent in a request header (never a URL),
 *     never logged, never returned, never NEXT_PUBLIC_.
 *   - No tools: no Google Search grounding, no browsing, no code execution. Gemini sees only the fact pack.
 *   - Off in production. MODELROOM_GEMINI=off turns it off on TEST.
 *   - A 429 means the free quota is used up: Gemini is paused until the next Pacific midnight. Billing is never
 *     touched from here; without billing the free tier refuses requests instead of charging.
 */
export const GEMINI_MODEL = "gemini-3.5-flash-lite";
const ENDPOINT = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`;
const TIMEOUT_MS = 15_000;

let pausedUntil = 0;

export type GeminiOutcome =
  | { ok: true; json: unknown; usage: { prompt: number; output: number } }
  | { ok: false; reason: "disabled" | "quota" | "error" | "timeout" | "blocked"; message: string };

export function geminiEnabled(): boolean {
  return !isProduction() && Boolean(process.env.GEMINI_API_KEY?.trim()) && process.env.MODELROOM_GEMINI !== "off";
}

export function geminiPaused(now = Date.now()): boolean {
  return now < pausedUntil;
}

/** Next midnight in America/Los_Angeles (Google's free-tier daily quota resets at Pacific midnight). */
export function nextPacificMidnight(now = new Date()): number {
  const f = new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles", hour: "numeric", minute: "numeric", second: "numeric", hourCycle: "h23" });
  const p = Object.fromEntries(f.formatToParts(now).map((x) => [x.type, Number(x.value)]));
  const secs = (24 - p.hour) * 3600 - p.minute * 60 - p.second;
  return now.getTime() + secs * 1000;
}

export function pauseForTests(until: number) {
  pausedUntil = until;
}

export async function generateJson(opts: { system: string; user: string; schema: object; maxOutputTokens: number; fetchImpl?: typeof fetch }): Promise<GeminiOutcome> {
  if (!geminiEnabled()) return { ok: false, reason: "disabled", message: "AI analysis isn't switched on for this site." };
  if (geminiPaused()) return { ok: false, reason: "quota", message: "Today's free AI allowance is used up. It resets at midnight Pacific." };
  const doFetch = opts.fetchImpl ?? fetch;
  let res: Response;
  try {
    res = await doFetch(ENDPOINT, {
      method: "POST",
      headers: { "content-type": "application/json", "x-goog-api-key": process.env.GEMINI_API_KEY!.trim() },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: opts.system }] },
        contents: [{ role: "user", parts: [{ text: opts.user }] }],
        generationConfig: { temperature: 0.2, maxOutputTokens: opts.maxOutputTokens, responseMimeType: "application/json", responseSchema: opts.schema },
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (e) {
    const timeout = e instanceof Error && (e.name === "TimeoutError" || e.name === "AbortError");
    return { ok: false, reason: timeout ? "timeout" : "error", message: timeout ? "The AI service took too long to answer." : "The AI service couldn't be reached." };
  }
  if (res.status === 429) {
    pausedUntil = nextPacificMidnight();
    return { ok: false, reason: "quota", message: "Today's free AI allowance is used up. It resets at midnight Pacific." };
  }
  if (!res.ok) return { ok: false, reason: "error", message: `The AI service returned an error (${res.status}).` };
  let body: { candidates?: { content?: { parts?: { text?: string }[] }; finishReason?: string }[]; usageMetadata?: { promptTokenCount?: number; candidatesTokenCount?: number }; promptFeedback?: { blockReason?: string } };
  try {
    body = await res.json();
  } catch {
    return { ok: false, reason: "error", message: "The AI service sent an unreadable answer." };
  }
  if (body.promptFeedback?.blockReason) return { ok: false, reason: "blocked", message: "The AI service declined this request." };
  const text = body.candidates?.[0]?.content?.parts?.map((p) => p.text ?? "").join("") ?? "";
  let json: unknown;
  try {
    json = JSON.parse(text);
  } catch {
    return { ok: false, reason: "error", message: "The AI answer wasn't in the expected format." };
  }
  return { ok: true, json, usage: { prompt: body.usageMetadata?.promptTokenCount ?? 0, output: body.usageMetadata?.candidatesTokenCount ?? 0 } };
}
