/**
 * The owner dashboard's eight sections. Server components only: they format what the loaders read and compute no new
 * statistics. Observed market data and model estimates are styled apart (parts.tsx); every model figure names its
 * version; sample gates are shown, never skipped.
 */
import type { PropMetrics, PropValidation } from "@/server/engine/board";
import type { DbResult } from "@/server/owner/db";
import type { OwnerFiles, SchedulerHealth, SportsbookData } from "@/server/owner/data";
import type { League } from "@/types/domain";
import { ago, Block, Estimated, Insufficient, Notice, n3, Observed, pct, Reliability, signed, Stat, Table, ts, UnavailableState } from "./parts";

const td = "px-2.5 py-1.5 text-right font-mono";
const tdl = "px-2.5 py-1.5 text-left";
const MARKET: Record<string, string> = { spread: "Spread", total: "Total", moneyline: "Moneyline" };
const lineText = (x: number | null, market = "spread") => (x == null ? "–" : x > 0 && market === "spread" ? `+${x}` : String(x));
const price = (x: number | null) => (x == null ? "–" : x > 0 ? `+${x}` : String(x));

function dbGate<T>(r: DbResult<T>): r is { ok: true; data: T } {
  return r.ok;
}

function DbMissing({ r, what }: { r: DbResult<unknown>; what: string }) {
  return r.ok ? null : <UnavailableState what={what} reason={r.reason} />;
}

/** The first persisted comparisons are not settled evidence: say when persistence began, every time. */
function PersistenceNote({ d }: { d: SportsbookData }) {
  return (
    <Notice tone="warn">
      Comparisons have been kept since {ts(d.comparisons.firstStoredAt)} (the persistence fix). Before that, runs computed them but stored nothing.
      These are unvalidated differences between the model and the books, not settled performance: settled scores need {250} graded games per market.
    </Notice>
  );
}

// ------------------------------------------------------------------ 1. line movement (observed market data only)
export function MovementSection({ sb, league }: { sb: DbResult<SportsbookData>; league: League }) {
  if (!dbGate(sb)) return <DbMissing r={sb} what="Sportsbook line movement" />;
  const r = sb.data.report?.payload;
  if (!r?.accumulation) return <UnavailableState what="Sportsbook line movement" reason="empty" />;
  const a = r.accumulation;
  const H = [...(r.line_histories ?? [])].sort((x, y) => Number(y.observations > 1) - Number(x.observations > 1) || Math.abs(y.line_change ?? 0) - Math.abs(x.line_change ?? 0) || x.commence_time.localeCompare(y.commence_time));
  const shown = H.slice(0, 60);
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <Stat label="Snapshot rows stored" value={sb.data.snapshots.rows.toLocaleString()} sub={`${a.fetches} fetches`} tone="market" />
        <Stat label="Collected" value={`${a.days_of_history} days`} sub={`${ts(a.first_collected_at)} → ${ts(a.last_collected_at)}`} />
        <Stat label="Games · books" value={`${a.games} · ${a.books}`} sub={`${a.games_matched_to_schedule} games matched to the schedule`} />
        <Stat label="Line series" value={a.series_game_book_market.toLocaleString()} sub={`${r.movement?.overall?.series_with_2plus_observations ?? 0} seen more than once`} />
      </div>
      <Block title="Movement by market" intro="Only series observed at least twice can move. Line change in points; probability change in no-vig percentage points. Observed values, no model involved.">
        <Table head={["Market", "Series", "Seen 2+ times", "Moved", "Mean |line change|", "Mean |no-vig change|"]}>
          {Object.entries(r.movement?.by_market ?? {}).map(([m, v]) => (
            <tr key={m}>
              <td className={tdl}>{MARKET[m] ?? m}</td><td className={td}>{v.series}</td><td className={td}>{v.series_with_2plus_observations}</td><td className={td}>{v.moved}</td>
              <td className={td}><Observed>{v.mean_abs_line_change ?? "–"}</Observed></td><td className={td}><Observed>{v.mean_abs_novig_change_pp != null ? `${v.mean_abs_novig_change_pp} pp` : "–"}</Observed></td>
            </tr>
          ))}
        </Table>
      </Block>
      <Block title="Line histories" intro={`Earliest and latest observation per game, book and market (${shown.length} of ${H.length}, moved series first). "Latest observed" is never a closing line: lines are fetched at set times, not at tip-off or kickoff.`}>
        <Table head={["Game", "Market", "Book", "Obs.", "Earliest", "Latest observed", "Change", "Direction"]}>
          {shown.map((h) => (
            <tr key={`${h.game_key}|${h.sportsbook}|${h.market}`}>
              <td className={`${tdl} whitespace-nowrap`}>{h.away} @ {h.home}<div className="text-[0.65rem] text-faint">{ts(h.commence_time)}</div></td>
              <td className={tdl}>{MARKET[h.market] ?? h.market}</td>
              <td className={tdl}>{h.sportsbook}</td>
              <td className={td}>{h.observations}</td>
              <td className={td}><Observed>{h.market === "moneyline" ? `${price(h.earliest_observed.price_a)}/${price(h.earliest_observed.price_b)}` : lineText(h.earliest_observed.line, h.market)}</Observed><div className="text-[0.65rem] text-faint">{ts(h.earliest_observed.collected_at)}</div></td>
              <td className={td}><Observed>{h.market === "moneyline" ? `${price(h.latest_observed.price_a)}/${price(h.latest_observed.price_b)}` : lineText(h.latest_observed.line, h.market)}</Observed><div className="text-[0.65rem] text-faint">{ts(h.latest_observed.collected_at)}</div></td>
              <td className={td}>{h.observations > 1 ? (h.market === "moneyline" ? (h.novig_a_change != null ? `${signed(h.novig_a_change * 100, 1)} pp` : "–") : signed(h.line_change, 1)) : <span className="text-faint">once</span>}</td>
              <td className={`${tdl} text-mute`}>{h.direction}</td>
            </tr>
          ))}
        </Table>
      </Block>
      <p className="text-[0.7rem] text-faint">Latest analysis run {ts(sb.data.report?.insertedAt)} · {league.toUpperCase()} · source odds.snapshots via odds.reports (private).</p>
    </div>
  );
}

// ------------------------------------------------------------------ 2. model vs market
export function VsMarketSection({ sb, league }: { sb: DbResult<SportsbookData>; league: League }) {
  if (!dbGate(sb)) return <DbMissing r={sb} what="Model versus market" />;
  const r = sb.data.report?.payload;
  if (!r?.accumulation) return <UnavailableState what="Model versus market" reason="empty" />;
  const a = r.accumulation;
  const C = [...(r.upcoming_latest_comparisons ?? [])].sort((x, y) => x.commence_time.localeCompare(y.commence_time) || x.market.localeCompare(y.market) || x.sportsbook.localeCompare(y.sportsbook)).slice(0, 80);
  return (
    <div className="space-y-6">
      <PersistenceNote d={sb.data} />
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <Stat label="Comparisons stored" value={sb.data.comparisons.rows.toLocaleString()} sub={`${a.comparisons.matched.toLocaleString()} matched in the latest run`} />
        <Stat label="Games with comparisons" value={`${a.games_with_comparisons.upcoming_or_unsettled} upcoming`} sub={`${a.games_with_comparisons.settled} settled`} />
        <Stat label="|Model − book|, upcoming" value={r.upcoming?.abs_model_minus_book_novig_pp ? `${r.upcoming.abs_model_minus_book_novig_pp.median} pp` : "–"} sub={r.upcoming?.abs_model_minus_book_novig_pp ? `median · 90th percentile ${r.upcoming.abs_model_minus_book_novig_pp.p90} pp` : "no upcoming comparisons"} />
        <Stat label="Not matched" value={Object.values(a.comparisons.not_matched).reduce((x, y) => x + y, 0)} sub={Object.entries(a.comparisons.not_matched).filter(([, n]) => n).map(([k, n]) => `${k.replaceAll("_", " ")} ${n}`).join(" · ") || "none"} />
      </div>
      <Block title="Settled evaluation" intro={`Scores appear only once a market has ${250} settled games, each scored at the books' latest pre-start line. Until then, counts only.`}>
        <Table head={["Market", "Settled games", "Progress", "Model log loss", "Book no-vig log loss", "Model − book (95% interval)", "Model Brier", "Book Brier"]}>
          {Object.entries(r.settled ?? {}).map(([m, s]) => (
            <tr key={m}>
              <td className={tdl}>{MARKET[m] ?? m}</td><td className={td}>{s.settled_games}</td><td className={td}>{s.progress_pct}% of {s.required_for_summary}</td>
              {s.model_log_loss == null ? <td colSpan={5} className={`${td} text-left`}><Insufficient note={s.status} /></td> : (
                <>
                  <td className={td}><Estimated>{n3(s.model_log_loss)}</Estimated></td><td className={td}><Observed>{n3(s.book_novig_log_loss)}</Observed></td>
                  <td className={td}>{signed(s.model_minus_book_log_loss, 4)} ({s.model_minus_book_log_loss_95ci?.map((v) => v.toFixed(4)).join(" to ")})</td>
                  <td className={td}><Estimated>{n3(s.model_brier)}</Estimated></td><td className={td}><Observed>{n3(s.book_novig_brier)}</Observed></td>
                </>
              )}
            </tr>
          ))}
        </Table>
      </Block>
      <Block title="Latest comparison per upcoming game, book and market" intro="The book's line and its no-vig probability as collected, beside the model's probability at that exact line from the latest game prediction recorded before the line was collected. The difference is a disagreement, not an edge.">
        {C.length ? (
          <Table head={["Game", "Market", "Book", "Line", "Book no-vig", "Model (excl. push)", "Model − book", "Line seen", "Model version · recorded"]}>
            {C.map((c) => (
              <tr key={`${c.game_id}|${c.sportsbook}|${c.market}`}>
                <td className={`${tdl} whitespace-nowrap`}>{c.away} @ {c.home}<div className="text-[0.65rem] text-faint">{ts(c.commence_time)}</div></td>
                <td className={tdl}>{MARKET[c.market] ?? c.market} <span className="text-faint">({c.side_a})</span></td>
                <td className={tdl}>{c.sportsbook}</td>
                <td className={td}><Observed>{c.market === "moneyline" ? `${price(c.price_a)}/${price(c.price_b)}` : lineText(c.line, c.market)}</Observed></td>
                <td className={td}><Observed>{pct(c.book_novig_a)}</Observed></td>
                <td className={td}><Estimated>{pct(c.model_prob_a_excl_push)}</Estimated></td>
                <td className={td}>{c.model_minus_book_novig_a_pp != null ? `${signed(c.model_minus_book_novig_a_pp, 1)} pp` : "–"}</td>
                <td className={td}>{ts(c.collected_at)}</td>
                <td className={td}><Estimated>{c.model_version ?? "?"}</Estimated><div className="text-[0.65rem] text-faint">{ts(c.model_generated_at)}</div></td>
              </tr>
            ))}
          </Table>
        ) : <UnavailableState what="Upcoming comparisons" reason="empty" />}
      </Block>
      <Notice>
        Closing-line value: {r.closing_line_value?.status ?? "disabled"} ({r.closing_line_value?.reason ?? "no genuine closing line"}). Player-prop prices are not stored yet, so props are not compared
        with any market here. No ROI, profit or expected-value figure is shown: no stakes were ever recorded.
      </Notice>
      <p className="text-[0.7rem] text-faint">{league.toUpperCase()} · source odds.comparisons and odds.reports (private) · latest run {ts(sb.data.report?.insertedAt)}.</p>
    </div>
  );
}

// ------------------------------------------------------------------ validation helpers (props)
const cats = (v: PropValidation) => Object.entries(v.markets ?? {});

function ValidationMissing({ v }: { v: PropValidation | null }) {
  if (v && !v.error && v.versions) return null;
  return <UnavailableState what="Prop validation" reason="empty" />;
}

function rulesText(v: PropValidation) {
  const r = v.rules;
  return r ? `Gates: ${r.min_player_games} player-games for averages, ${r.min_ladder_rows} ladder rows for Brier and log loss, ${r.min_bin} rows per calibration bin, ${r.min_side} per Over/Under side.` : "";
}

function Metric({ m, k, d = 3 }: { m: PropMetrics | undefined; k: "mae" | "bias" | "brier" | "log_loss" | "calibration_error"; d?: number }) {
  if (!m || !m.player_games) return <span className="text-faint">–</span>;
  const v = m[k];
  if (v == null) return <Insufficient note={k === "mae" || k === "bias" ? m.withheld_mean : m.withheld_ladder} />;
  return <Estimated>{k === "bias" ? signed(v, 2) : k === "calibration_error" ? pct(v) : v.toFixed(d)}</Estimated>;
}

// ------------------------------------------------------------------ 3. prop performance by category (active model)
export function PropsSection({ files, league }: { files: OwnerFiles; league: League }) {
  const v = files.validation;
  if (!v || v.error || !v.versions) return <ValidationMissing v={v} />;
  const act = v.versions[v.active ?? ""];
  return (
    <div className="space-y-5">
      <Notice>Active model <Estimated>{league.toUpperCase()} props {v.active}</Estimated> graded against what happened, from projections recorded before each game. Recent = last {v.recent_window?.days ?? 14} days. {rulesText(v)}</Notice>
      <Table head={["Category", "Player-games", "MAE", "Bias (proj − actual)", "Over leans: happened vs expected", "Under leans: happened vs expected", "Recent player-games", "Recent bias"]}>
        {cats(v).map(([k, label]) => {
          const all = act?.live?.[k]?.all; const rec = act?.live?.[k]?.recent; const ou = all?.over_under;
          const side = (s: { n: number; predicted: number | null; hit_rate: number | null } | undefined) =>
            !s ? "–" : s.hit_rate == null || s.predicted == null ? <span><Insufficient /> <span className="text-faint">(n {s.n})</span></span> : <span><Observed>{pct(s.hit_rate)}</Observed> vs <Estimated>{pct(s.predicted)}</Estimated> <span className="text-faint">(n {s.n})</span></span>;
          return (
            <tr key={k}>
              <td className={tdl}>{label}</td>
              <td className={td}>{all?.player_games ?? 0}</td>
              <td className={td}><Metric m={all} k="mae" d={2} /></td>
              <td className={td}><Metric m={all} k="bias" /></td>
              <td className={td}>{side(ou?.over)}</td>
              <td className={td}>{side(ou?.under)}</td>
              <td className={td}>{rec?.player_games ?? 0}</td>
              <td className={td}><Metric m={rec} k="bias" /></td>
            </tr>
          );
        })}
      </Table>
      <p className="text-[0.7rem] text-faint">Graded span {ts(act?.live_span?.first_game)} → {ts(act?.live_span?.last_game)} · validation built {ts(v.generated_at)} · source props_monitor_{league}.json.</p>
    </div>
  );
}

// ------------------------------------------------------------------ 4. calibration, Brier, log loss
export function CalibrationSection({ files, league }: { files: OwnerFiles; league: League }) {
  const v = files.validation;
  const g = files.performance?.games?.win_prob;
  const minBin = v?.rules?.min_bin ?? 30;
  return (
    <div className="space-y-6">
      <Block title="Game model: win probability" intro="Every game prediction recorded before tip-off or kickoff, graded once final.">
        {g ? (
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <Stat label="Games graded" value={g.n} sub="small samples are noisy" />
            <Stat label="Brier" value={g.brier.toFixed(4)} tone="model" sub={`n ${g.n} · lower is better; 0.25 = coin flip`} />
            <Stat label="Log loss" value={g.log_loss.toFixed(4)} tone="model" sub={`n ${g.n} · lower is better; 0.693 = coin flip`} />
            <Stat label="Average predicted vs home win rate" value={<><Estimated>{pct(g.avg_predicted)}</Estimated> / <Observed>{pct(g.hit_rate)}</Observed></>} />
          </div>
        ) : <UnavailableState what="Game-model grading" reason="empty" />}
      </Block>
      {!v || v.error || !v.versions ? <ValidationMissing v={v} /> : (
        <Block title={`Player props: active model ${v.active}`} intro={`Live: projections graded so far. Backtest: held-out seasons for this version (${v.versions[v.active ?? ""]?.historical?.test_seasons?.join(", ") ?? "none"}), shown separately and never blended. Calibration error = average gap between predicted and observed across bins.`}>
          <Table head={["Category", "Ladder rows", "Live Brier", "Live log loss", "Live calibration error", "Backtest log loss", "Backtest recent-form baseline"]}>
            {cats(v).map(([k, label]) => {
              const all = v.versions![v.active ?? ""]?.live?.[k]?.all; const h = v.versions![v.active ?? ""]?.historical?.markets?.[k];
              return (
                <tr key={k}>
                  <td className={tdl}>{label}</td><td className={td}>{all?.ladder_rows ?? 0}</td>
                  <td className={td}><Metric m={all} k="brier" /></td><td className={td}><Metric m={all} k="log_loss" /></td><td className={td}><Metric m={all} k="calibration_error" /></td>
                  <td className={td}>{h?.log_loss != null ? <Estimated>{n3(h.log_loss)}</Estimated> : "–"}</td><td className={td}>{h?.baseline_log_loss != null ? n3(h.baseline_log_loss) : "–"}</td>
                </tr>
              );
            })}
          </Table>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {cats(v).map(([k, label]) => {
              const cal = v.versions![v.active ?? ""]?.live?.[k]?.all?.calibration;
              return (
                <div key={k} className="rounded-lg bg-navy-900 p-3">
                  <div className="mb-1 text-xs font-600 text-ink">{label}</div>
                  {cal?.length ? <Reliability bins={cal} minN={minBin} label={`${league.toUpperCase()} ${label}`} /> : <p className="text-xs text-faint"><Insufficient /></p>}
                </div>
              );
            })}
          </div>
        </Block>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ 5. active vs shadow
export function ShadowSection({ files, league }: { files: OwnerFiles; league: League }) {
  const v = files.validation;
  if (!v || v.error || !v.versions) return <ValidationMissing v={v} />;
  const order = [v.active ?? "", ...(v.shadows ?? [])].filter((x) => v.versions![x]);
  return (
    <div className="space-y-5">
      <Notice>
        Active <Estimated>{v.active}</Estimated> is published; shadows <Estimated>{(v.shadows ?? []).join(", ") || "none"}</Estimated> are recorded beside it and never shown to subscribers.
        Each version is graded on the games it recorded, so sample sizes can differ; compare where both pass the gates. No shadow is promoted without your approval.
      </Notice>
      {cats(v).map(([k, label]) => (
        <Block key={k} title={label}>
          <Table head={["Version", "Role", "Player-games", "MAE", "Bias", "Ladder rows", "Brier", "Log loss", "Calibration error"]}>
            {order.map((ver) => {
              const all = v.versions![ver]?.live?.[k]?.all;
              return (
                <tr key={ver}>
                  <td className={tdl}><Estimated>{ver}</Estimated></td><td className={tdl}>{v.versions![ver].role}</td>
                  <td className={td}>{all?.player_games ?? 0}</td><td className={td}><Metric m={all} k="mae" d={2} /></td><td className={td}><Metric m={all} k="bias" /></td>
                  <td className={td}>{all?.ladder_rows ?? 0}</td><td className={td}><Metric m={all} k="brier" /></td><td className={td}><Metric m={all} k="log_loss" /></td><td className={td}><Metric m={all} k="calibration_error" /></td>
                </tr>
              );
            })}
          </Table>
        </Block>
      ))}
      <p className="text-[0.7rem] text-faint">{league.toUpperCase()} · source props_monitor_{league}.json (graded from the prediction ledgers) · built {ts(v.generated_at)}.</p>
    </div>
  );
}

// ------------------------------------------------------------------ 6. model-version history
export function VersionsSection({ files, league }: { files: OwnerFiles; league: League }) {
  const v = files.validation;
  if (!v || v.error || !v.versions) return <ValidationMissing v={v} />;
  const rank = { active: 0, shadow: 1, previous: 2 } as const;
  const vs = Object.entries(v.versions).sort(([a, x], [b, y]) => rank[x.role] - rank[y.role] || b.localeCompare(a));
  return (
    <div className="space-y-6">
      <Notice>Backtest = held-out seasons replayed before the version went live. Live = projections the version recorded before real games. Kept in separate columns, never blended. Records are graded as they were written; nothing is re-scored.</Notice>
      {vs.map(([ver, x]) => (
        <Block key={ver} title={`${league.toUpperCase()} props ${ver}`} intro={<>
          {x.role === "active" ? "Active (published)" : x.role === "shadow" ? "Shadow (recorded, not published)" : "Earlier version (no longer running)"} ·
          live records {x.live_span ? `${ts(x.live_span.first_game)} → ${ts(x.live_span.last_game)}` : "none"} ·
          backtest {x.historical ? `seasons ${x.historical.test_seasons.join(", ")} (${x.historical.source})` : "none on file"}{x.historical_note ? ` · ${x.historical_note}` : ""}
        </>}>
          <Table head={["Category", "Backtest ladder rows", "Backtest log loss", "Backtest baseline", "Live ladder rows", "Live log loss", "Live player-games", "Live bias"]}>
            {cats(v).map(([k, label]) => {
              const h = x.historical?.markets?.[k]; const all = x.live?.[k]?.all;
              return (
                <tr key={k}>
                  <td className={tdl}>{label}</td>
                  <td className={td}>{h?.ladder_rows?.toLocaleString() ?? "–"}</td><td className={td}>{h?.log_loss != null ? <Estimated>{n3(h.log_loss)}</Estimated> : "–"}</td><td className={td}>{n3(h?.baseline_log_loss)}</td>
                  <td className={td}>{all?.ladder_rows ?? 0}</td><td className={td}><Metric m={all} k="log_loss" /></td><td className={td}>{all?.player_games ?? 0}</td><td className={td}><Metric m={all} k="bias" /></td>
                </tr>
              );
            })}
          </Table>
        </Block>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ 7. freshness and scheduler
export function FreshnessSection({ files, sched, sb, now, league }: { files: OwnerFiles; sched: DbResult<SchedulerHealth | null>; sb: DbResult<SportsbookData>; now: number; league: League }) {
  const stale = (iso: string | null | undefined, hours: number) => !iso || (now - Date.parse(iso)) / 3.6e6 > hours;
  const row = (label: string, iso: string | null | undefined, hours: number, extra?: string) => (
    <tr key={label}>
      <td className={tdl}>{label}</td><td className={td}>{ts(iso)}</td>
      <td className={`${td} ${stale(iso, hours) ? "text-edge" : "text-mute"}`}>{ago(iso, now)}</td>
      <td className={`${tdl} text-faint`}>{stale(iso, hours) ? `older than ${hours} h` : "within expected interval"}{extra ? ` · ${extra}` : ""}</td>
    </tr>
  );
  const kinds = Object.entries(files.refresh?.last_success_by_kind ?? {});
  const acc = sb.ok ? sb.data.report?.payload.accumulation : undefined;
  return (
    <div className="space-y-6">
      <Block title={`Data freshness (${league.toUpperCase()})`}>
        <Table head={["Data", "Last updated", "Age", "Status"]}>
          {row("Game projections board", files.boards.games?.at, 18, files.boards.games ? `model ${files.boards.games.version}` : undefined)}
          {row("Player-prop board", files.boards.props?.at, 18, files.boards.props ? `model ${files.boards.props.version}` : undefined)}
          {row("Injury feed", files.injuriesAt, 12)}
          {row("Prop validation", files.validation?.generated_at, 18)}
          {row("Sportsbook analysis (private)", sb.ok ? sb.data.report?.insertedAt : null, 18)}
          {row("Sportsbook lines collected", acc?.last_collected_at, 30, "odds are fetched at 7 AM and noon PT only")}
        </Table>
      </Block>
      <Block title="Refresh slots" intro="Last successful run of each kind of scheduled refresh, from the refresh log.">
        {kinds.length ? (
          <Table head={["Kind", "Slot", "Finished", "Age", "Run"]}>
            {kinds.map(([k, s]) => (
              <tr key={k}><td className={tdl}>{k}</td><td className={`${tdl} font-mono`}>{s.slot}</td><td className={td}>{ts(s.at)}</td><td className={td}>{ago(s.at, now)}</td><td className={`${tdl} text-faint`}>{s.note ?? ""}</td></tr>
            ))}
          </Table>
        ) : <UnavailableState what="Refresh log" reason="empty" />}
        {files.refresh?.recent_failures?.length ? (
          <p className="text-xs text-mute">Recent failures: {files.refresh.recent_failures.slice(-5).map((f) => `${f.slot} (${ts(f.at)})`).join(" · ")}</p>
        ) : null}
      </Block>
      <Block title="Scheduler health" intro="From the scheduler.health view in the TEST database: dispatches to GitHub Actions. The dispatch token itself is never read, only whether it exists.">
        {!sched.ok ? <UnavailableState what="Scheduler health" reason={sched.reason} /> : !sched.data ? <UnavailableState what="Scheduler health" reason="empty" /> : (
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Scheduler" value={sched.data.enabled} tone={sched.data.enabled === "on" ? "ink" : "edge"} />
            <Stat label="Last dispatch" value={ago(sched.data.last_dispatch, now)} sub={ts(sched.data.last_dispatch)} />
            <Stat label="Last accepted (204)" value={ago(sched.data.last_accepted, now)} sub={ts(sched.data.last_accepted)} />
            <Stat label="Failures, 24 h" value={sched.data.failures_24h} tone={sched.data.failures_24h ? "edge" : "ink"} />
            <Stat label="Awaiting response" value={sched.data.awaiting_response} />
            <Stat label="Dispatch token stored" value={sched.data.token_stored ? "yes" : "no"} tone={sched.data.token_stored ? "ink" : "edge"} />
          </div>
        )}
      </Block>
      <Block title="Odds API usage and storage" intro="Credits are read from the usage log the refresh writes; the dashboard never calls the Odds API.">
        {!sb.ok ? <UnavailableState what="Odds usage and storage" reason={sb.reason} /> : (
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <Stat label="Credits remaining (last reported)" value={String(acc?.odds_api?.credits_remaining_last_reported ?? "–")} sub={acc?.odds_api?.as_of ? `as of ${ts(acc.odds_api.as_of)}` : undefined} />
            <Stat label="Credits used this month (logged)" value={acc?.odds_api?.credits_used_this_month_logged ?? "–"} sub={`${acc?.odds_api?.calls_this_month ?? 0} calls`} />
            <Stat label="Comparisons persisted" value={sb.data.comparisons.rows.toLocaleString()} sub={`analysis runs stored: ${sb.data.runs.length}${sb.data.runs.length === 12 ? "+" : ""}`} />
            <Stat label="Snapshot rows stored" value={sb.data.snapshots.rows.toLocaleString()} sub={`last stored ${ts(sb.data.snapshots.lastStoredAt)}`} />
          </div>
        )}
      </Block>
    </div>
  );
}

// ------------------------------------------------------------------ 8. private sportsbook-level analysis
export function BooksSection({ sb, league }: { sb: DbResult<SportsbookData>; league: League }) {
  if (!dbGate(sb)) return <DbMissing r={sb} what="Sportsbook-level analysis" />;
  const r = sb.data.report?.payload;
  if (!r?.accumulation) return <UnavailableState what="Sportsbook-level analysis" reason="empty" />;
  const rows = r.coverage_rows_by_book ?? {};
  const mv = r.movement_by_book ?? {};
  const books = [...new Set([...Object.keys(rows), ...Object.keys(mv)])].sort();
  const latest = r.upcoming_latest_comparisons ?? [];
  const missing = r.coverage_detail?.missing_by_game ?? [];
  const staleRows = r.coverage_detail?.stale_rows ?? [];
  return (
    <div className="space-y-6">
      <Notice tone="warn">Private to the owner. Sportsbook names and book-level figures appear only on this page: never on subscriber pages, public reports or the repository.</Notice>
      {!books.length ? <UnavailableState what="Book-level detail" reason="empty" /> : (
        <Block title="Coverage and movement by book" intro="Rows collected, series observed more than once, and how far observed lines moved. Upcoming comparisons = latest comparison per upcoming game and market for that book.">
          <Table head={["Book", "Rows collected", "Series", "Seen 2+ times", "Moved", "Mean |line change|", "Mean |no-vig change|", "Upcoming comparisons"]}>
            {books.map((b) => (
              <tr key={b}>
                <td className={tdl}>{b}</td><td className={td}>{rows[b] ?? 0}</td><td className={td}>{mv[b]?.series ?? 0}</td><td className={td}>{mv[b]?.series_with_2plus_observations ?? 0}</td><td className={td}>{mv[b]?.moved ?? 0}</td>
                <td className={td}><Observed>{mv[b]?.mean_abs_line_change ?? "–"}</Observed></td><td className={td}><Observed>{mv[b]?.mean_abs_novig_change_pp != null ? `${mv[b].mean_abs_novig_change_pp} pp` : "–"}</Observed></td>
                <td className={td}>{latest.filter((c) => c.sportsbook === b).length}</td>
              </tr>
            ))}
          </Table>
        </Block>
      )}
      <Block title="Settled results by book" intro="Not reported yet. Settled scoring uses the books' consensus per market and needs 250 graded games per market before any score is shown; a per-book split would need the same gate per book.">
        <p className="text-xs text-faint">Insufficient sample: {Object.entries(r.settled ?? {}).map(([m, s]) => `${MARKET[m] ?? m} ${s.settled_games} of ${s.required_for_summary}`).join(" · ")}.</p>
      </Block>
      <Block title="Missing and stale lines" intro={`Games where a book listed in that fetch had no line, or lacked a market; and rows whose book timestamp was older than the stale rule (${r.coverage?.stale_rule ?? ""}).`}>
        <div className="grid gap-4 lg:grid-cols-2">
          <Table head={["Fetch", "Game", "Missing books", "Missing markets"]}>
            {missing.slice(0, 30).map((m, i) => (
              <tr key={i}><td className={td}>{ts(m.fetch)}</td><td className={`${tdl} font-mono text-[0.68rem]`}>{m.game_key}</td><td className={tdl}>{m.missing_books.join(", ") || "–"}</td><td className={tdl}>{Object.entries(m.missing_markets_by_book).map(([b, ms]) => `${b}: ${ms.join("/")}`).join("; ") || "–"}</td></tr>
            ))}
            {!missing.length ? <tr><td colSpan={4} className={`${tdl} text-faint`}>None</td></tr> : null}
          </Table>
          <Table head={["Fetch", "Game", "Book", "Market", "Book update age"]}>
            {staleRows.slice(0, 30).map((s, i) => (
              <tr key={i}><td className={td}>{ts(s.fetch)}</td><td className={`${tdl} font-mono text-[0.68rem]`}>{s.game_key}</td><td className={tdl}>{s.sportsbook}</td><td className={tdl}>{MARKET[s.market] ?? s.market}</td><td className={td}>{s.book_age_hours} h</td></tr>
            ))}
            {!staleRows.length ? <tr><td colSpan={5} className={`${tdl} text-faint`}>None</td></tr> : null}
          </Table>
        </div>
      </Block>
      <p className="text-[0.7rem] text-faint">{league.toUpperCase()} · source odds.reports (private) · run {ts(sb.data.report?.insertedAt)}.</p>
    </div>
  );
}
