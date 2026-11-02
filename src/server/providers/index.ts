import "server-only";
import type { DataProvider } from "./types";
import { demoProvider } from "./demo";

/**
 * Picks the active data provider.
 *
 * Today only the demo provider exists. When the NFL/NBA engines and a
 * Supabase-backed store are ready, add a provider here (for example
 * `supabaseProvider`) and select it with MODEL_ROOM_DATA_SOURCE=live.
 */
export function getProvider(): DataProvider {
  const source = process.env.MODEL_ROOM_DATA_SOURCE ?? "demo";
  switch (source) {
    case "demo":
      return demoProvider;
    default:
      throw new Error(
        `MODEL_ROOM_DATA_SOURCE="${source}" has no provider yet. Only "demo" is available in Phase 1.`,
      );
  }
}
