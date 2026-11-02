import { EngineNotImplementedError, type GameModelEngine } from "../types";

/** NBA engine placeholder. See src/engines/README.md for the build plan. */
export const nbaEngine: GameModelEngine = {
  league: "nba",
  version: "0.0.0-unimplemented",
  async projectGames() {
    throw new EngineNotImplementedError("nba");
  },
};
