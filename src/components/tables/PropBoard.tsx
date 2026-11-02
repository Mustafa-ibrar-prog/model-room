import type { League } from "@/types/domain";
import { Unavailable } from "@/components/ui/primitives";

/** Player props aren't modeled yet. Shown as unavailable rather than with placeholder numbers. */
export function PropBoard({ league }: { league: League }) {
  return (
    <Unavailable
      title={`${league.toUpperCase()} player props aren't available yet`}
      body="Model Room doesn't project player props yet. This section will show the posted line next to a model projection once a player model is built and validated."
    />
  );
}
