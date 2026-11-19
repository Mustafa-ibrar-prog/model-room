/**
 * Four sports sections, kept apart on purpose: player props and game predictions are different things and
 * never share a page. Plans stay reachable from the header button and the account menu.
 */
export const NAV = [
  { href: "/", label: "Home" },
  { href: "/nba-props", label: "NBA Props" },
  { href: "/nfl-props", label: "NFL Props" },
  { href: "/nba", label: "NBA" },
  { href: "/nfl", label: "NFL" },
  { href: "/pick-of-the-day", label: "Pick of the Day" },
  { href: "/performance", label: "Performance" },
] as const;
