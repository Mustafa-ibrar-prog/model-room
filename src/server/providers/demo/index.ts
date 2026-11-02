import "server-only";
import type { DataProvider, RawGame, RawInjury, RawProp, RawRating } from "../types";
import type { DailyInsight, League, Team } from "@/types/domain";
import { NBA_TEAMS as B, NFL_TEAMS as F } from "./teams";

/**
 * DEMONSTRATION DATA.
 * Every team, player and number below is invented to exercise the interface.
 * Nothing here is a prediction, and no modeling engine produced it.
 */

function game(
  league: League,
  id: string,
  slot: string,
  away: Team,
  home: Team,
  market: [spread: number, open: number, total: number],
  model: [spread: number, total: number, awayPts: number, homePts: number],
  matchupNote: string,
): RawGame {
  return {
    id,
    league,
    slot,
    away,
    home,
    marketSpread: market[0],
    openingSpread: market[1],
    marketTotal: market[2],
    modelSpread: model[0],
    modelTotal: model[1],
    projectedScore: { away: model[2], home: model[3] },
    matchupNote,
  };
}

const NFL_GAMES: RawGame[] = [
  game("nfl", "nfl-d1", "Sun 10:00 AM", F.BOI, F.ALB, [-3.5, -2.5, 44.5], [-6.0, 46.5, 20.3, 26.2], "Albany's pass rush against a Boise line missing its left tackle drives most of the gap."),
  game("nfl", "nfl-d2", "Sun 10:00 AM", F.OMA, F.CMB, [2.5, 3.0, 41.0], [1.5, 40.0, 20.8, 19.2], "Two slow-tempo offenses. The model sees Omaha's run game as the steadier unit."),
  game("nfl", "nfl-d3", "Sun 1:05 PM", F.RIC, F.TUC, [-7.0, -6.5, 48.5], [-6.5, 51.0, 22.3, 28.7], "Tucson indoors with a rested secondary. The total is where the model disagrees."),
  game("nfl", "nfl-d4", "Sun 1:25 PM", F.HFD, F.SPK, [-1.0, -2.0, 43.5], [-1.5, 42.5, 20.5, 22.0], "Close to the market on both numbers. A pass at current prices."),
  game("nfl", "nfl-d5", "Sun 5:20 PM", F.RNO, F.AUS, [-4.5, -4.5, 46.0], [-2.0, 45.0, 21.5, 23.5], "Austin's red-zone defense has regressed in the demo ratings, trimming the home edge."),
];

const NBA_GAMES: RawGame[] = [
  game("nba", "nba-d1", "Mon 4:00 PM", B.FRE, B.TAC, [-5.5, -4.0, 226.5], [-8.0, 229.0, 110.5, 118.5], "Tacoma's bench minutes rate well above Fresno's second unit."),
  game("nba", "nba-d2", "Mon 4:30 PM", B.ANC, B.LOU, [1.5, 2.0, 218.0], [0.5, 214.5, 107.5, 107.0], "Both teams bottom-ten in pace. The model leans under."),
  game("nba", "nba-d3", "Mon 5:00 PM", B.RAL, B.ELP, [-3.0, -3.0, 231.5], [-3.5, 232.0, 114.3, 117.7], "Market and model agree. No edge worth acting on."),
  game("nba", "nba-d4", "Mon 6:00 PM", B.PVD, B.WIC, [-2.0, -1.0, 222.0], [1.0, 224.5, 112.8, 111.8], "Wichita on the second night of a back-to-back flips the side."),
  game("nba", "nba-d5", "Mon 7:30 PM", B.MAD, B.HNL, [-6.5, -7.5, 235.0], [-7.0, 238.5, 115.8, 122.7], "Honolulu's pace pushes the projected total above the posted number."),
];

const INJURIES: RawInjury[] = [
  { id: "i1", league: "nfl", player: "D. Hollis", team: F.BOI, position: "LT", status: "Out", detail: "Ankle", spreadImpact: 1.5, totalImpact: -0.5 },
  { id: "i2", league: "nfl", player: "M. Okafor", team: F.TUC, position: "WR", status: "Questionable", detail: "Hamstring", spreadImpact: 0.5, totalImpact: -1.0 },
  { id: "i3", league: "nfl", player: "R. Castellano", team: F.AUS, position: "QB", status: "Probable", detail: "Shoulder", spreadImpact: 0.0, totalImpact: 0.0 },
  { id: "i4", league: "nfl", player: "J. Whitfield", team: F.CMB, position: "CB", status: "Doubtful", detail: "Concussion protocol", spreadImpact: 0.5, totalImpact: 1.0 },
  { id: "i5", league: "nfl", player: "T. Brennan", team: F.HFD, position: "RB", status: "Out", detail: "Knee", spreadImpact: 0.5, totalImpact: -0.5 },
  { id: "i6", league: "nba", player: "K. Amari", team: B.WIC, position: "G", status: "Out", detail: "Rest", spreadImpact: 2.5, totalImpact: -2.0 },
  { id: "i7", league: "nba", player: "L. Vasquez", team: B.FRE, position: "F", status: "Day-to-day", detail: "Back", spreadImpact: 1.0, totalImpact: -1.5 },
  { id: "i8", league: "nba", player: "S. Duchene", team: B.ANC, position: "C", status: "Questionable", detail: "Wrist", spreadImpact: 1.5, totalImpact: -2.5 },
  { id: "i9", league: "nba", player: "A. Mbeki", team: B.HNL, position: "G", status: "Probable", detail: "Illness", spreadImpact: 0.0, totalImpact: 0.0 },
];

function prop(id: string, league: League, player: string, team: Team, opponent: Team, market: string, line: number, projection: number, overShare: number, low: number, high: number): RawProp {
  return { id, league, player, team, opponent, market, line, projection, overShare, range: { low, high } };
}

const PROPS: RawProp[] = [
  prop("p1", "nfl", "C. Redmond", F.ALB, F.BOI, "Passing yards", 245.5, 268.0, 0.61, 205, 330),
  prop("p2", "nfl", "E. Tran", F.TUC, F.RIC, "Receiving yards", 64.5, 71.5, 0.56, 38, 104),
  prop("p3", "nfl", "B. Lindqvist", F.OMA, F.CMB, "Rushing yards", 72.5, 66.0, 0.42, 41, 92),
  prop("p4", "nfl", "N. Abara", F.AUS, F.RNO, "Receptions", 5.5, 6.2, 0.58, 3, 9),
  prop("p5", "nba", "G. Petrov", B.TAC, B.FRE, "Points", 24.5, 27.1, 0.59, 18, 36),
  prop("p6", "nba", "I. Salazar", B.LOU, B.ANC, "Rebounds", 9.5, 8.6, 0.41, 5, 13),
  prop("p7", "nba", "W. Osei", B.HNL, B.MAD, "Assists", 7.5, 8.3, 0.57, 4, 12),
  prop("p8", "nba", "F. Kowalczyk", B.ELP, B.RAL, "3-pointers made", 2.5, 2.7, 0.52, 0, 6),
];

function rating(team: Team, league: League, overall: number, offense: number, defense: number, pace: number, sos: number): RawRating {
  return { team, league, overall, offense, defense, pace, scheduleStrength: sos };
}

const RATINGS: RawRating[] = [
  rating(F.ALB, "nfl", 6.8, 4.1, 2.7, 61.2, 0.4),
  rating(F.TUC, "nfl", 5.9, 4.6, 1.3, 64.0, -0.3),
  rating(F.AUS, "nfl", 3.2, 2.0, 1.2, 62.5, 0.9),
  rating(F.SPK, "nfl", 1.8, 0.4, 1.4, 59.8, 0.1),
  rating(F.OMA, "nfl", 0.6, -0.2, 0.8, 58.1, -0.6),
  rating(F.HFD, "nfl", -0.4, 0.9, -1.3, 63.3, 0.2),
  rating(F.CMB, "nfl", -1.1, -1.4, 0.3, 57.4, 0.7),
  rating(F.RNO, "nfl", -2.3, -0.8, -1.5, 60.9, -0.2),
  rating(F.RIC, "nfl", -3.6, -1.9, -1.7, 62.0, 0.5),
  rating(F.BOI, "nfl", -4.9, -2.6, -2.3, 59.0, -0.8),
  rating(B.TAC, "nba", 7.4, 118.9, 111.2, 100.4, 0.6),
  rating(B.HNL, "nba", 5.1, 119.6, 114.1, 103.8, -0.2),
  rating(B.ELP, "nba", 3.0, 116.2, 112.9, 99.1, 0.3),
  rating(B.RAL, "nba", 2.2, 115.0, 112.6, 98.7, 0.1),
  rating(B.WIC, "nba", 0.9, 114.3, 113.5, 97.5, -0.4),
  rating(B.LOU, "nba", -0.7, 112.1, 112.9, 96.2, 0.8),
  rating(B.PVD, "nba", -1.9, 113.4, 115.2, 99.9, -0.1),
  rating(B.MAD, "nba", -2.8, 114.8, 117.4, 102.6, 0.2),
  rating(B.ANC, "nba", -4.1, 110.6, 114.8, 95.8, -0.5),
  rating(B.FRE, "nba", -5.6, 109.9, 115.6, 98.2, 0.4),
];

const INSIGHTS: DailyInsight[] = [
  { id: "n1", league: "nfl", title: "Pass protection is the story in Albany", body: "With Boise's starting left tackle ruled out, the demo model moves Albany 1.5 points. That accounts for most of the gap against the posted line." },
  { id: "n2", league: "nba", title: "Back-to-backs flip a side in Wichita", body: "Wichita plays its second game in two nights and rests a starting guard. The demo model has Providence as a small favorite while the market still has Wichita laying 2." },
  { id: "n3", league: "nfl", title: "Tucson total sits above the market", body: "Indoor conditions and two top-ten passing offenses in the demo ratings push the projected total 2.5 points over the posted number." },
];

const byLeague = <T extends { league: League }>(rows: T[], league: League) => rows.filter((r) => r.league === league);

export const demoProvider: DataProvider = {
  info: {
    source: "demo",
    name: "Model Room demo dataset",
    note: "Demonstration data. Teams, players and numbers are fictional and are not projections.",
  },
  async getGames(league) {
    return league === "nfl" ? NFL_GAMES : NBA_GAMES;
  },
  async getInjuries(league) {
    return byLeague(INJURIES, league);
  },
  async getProps(league) {
    return byLeague(PROPS, league);
  },
  async getRatings(league) {
    return byLeague(RATINGS, league);
  },
  async getInsights() {
    return INSIGHTS;
  },
};
