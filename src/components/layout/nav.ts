/**
 * The whole site, in four places. Everything that used to be its own nav item is reachable from
 * inside one of them: player props are the players inside a game, model-vs-market is the line beside
 * the projection on a player, yesterday's results and the injury feed live under Performance and on
 * the player's own page. Plans stay reachable from the header button and the account menu.
 */
export const NAV = [
  { href: "/", label: "Home" },
  { href: "/nba", label: "NBA" },
  { href: "/nfl", label: "NFL" },
  { href: "/performance", label: "Performance" },
] as const;
