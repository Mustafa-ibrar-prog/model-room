import type { Team } from "@/types/domain";

/**
 * FICTIONAL teams for demonstration only. Names are invented so demo numbers
 * can never be mistaken for projections on real NFL or NBA games.
 */
function t(abbr: string, city: string, name: string): Team {
  return { id: abbr.toLowerCase(), abbr, city, name };
}

export const NFL_TEAMS = {
  ALB: t("ALB", "Albany", "Anchors"),
  BOI: t("BOI", "Boise", "Bison"),
  CMB: t("CMB", "Columbus", "Comets"),
  OMA: t("OMA", "Omaha", "Ospreys"),
  TUC: t("TUC", "Tucson", "Thunder"),
  RIC: t("RIC", "Richmond", "Rails"),
  SPK: t("SPK", "Spokane", "Summit"),
  HFD: t("HFD", "Hartford", "Harriers"),
  AUS: t("AUS", "Austin", "Armada"),
  RNO: t("RNO", "Reno", "Rattlers"),
} as const;

export const NBA_TEAMS = {
  TAC: t("TAC", "Tacoma", "Tides"),
  FRE: t("FRE", "Fresno", "Flyers"),
  LOU: t("LOU", "Louisville", "Lanterns"),
  ANC: t("ANC", "Anchorage", "Aurora"),
  ELP: t("ELP", "El Paso", "Embers"),
  RAL: t("RAL", "Raleigh", "Ridge"),
  WIC: t("WIC", "Wichita", "Wolves"),
  PVD: t("PVD", "Providence", "Pines"),
  HNL: t("HNL", "Honolulu", "Swell"),
  MAD: t("MAD", "Madison", "Monarchs"),
} as const;
