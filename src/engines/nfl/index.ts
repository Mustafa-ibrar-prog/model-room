import { EngineNotImplementedError, type GameModelEngine } from "../types";

/** NFL engine placeholder. See src/engines/README.md for the build plan. */
export const nflEngine: GameModelEngine = {
  league: "nfl",
  version: "0.0.0-unimplemented",
  async projectGames() {
    throw new EngineNotImplementedError("nfl");
  },
};
