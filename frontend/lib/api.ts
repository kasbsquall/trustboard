// 127.0.0.1 rather than localhost. Node resolves localhost to ::1 first, and
// uvicorn binds IPv4 only unless told otherwise, so the default fell straight
// through to "Standings unavailable" on a machine where everything was actually
// running. Set NEXT_PUBLIC_API_URL for any real deployment; it is read at build
// time because the browser is what calls it.
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export interface Team {
  domain_name: string;
  domain_urn: string | null;
  week_of: string;
  trust_score: number;
  assertions_passing_pct: number | null;
  freshness_score: number | null;
  documentation_score: number | null;
  rank_this_week: number | null;
  rank_last_week: number | null;
  score_last_week: number | null;
  ownership_score: number | null;
  /** Share of the scoring weight backed by a signal that was present (0-1). */
  signal_coverage: number | null;
  score_version: string | null;
  dataset_count: number | null;
  /** How many of those datasets could be judged at all. */
  rated_dataset_count: number | null;
  /** False when TrustBoard could not judge the team; the score then means nothing. */
  rated: boolean | null;
  /** True when the row was authored to give the demo a trend, not measured. */
  synthetic: boolean;
  spark: number[];
}

export interface LeaderboardResponse {
  teams: Team[];
  team_of_the_week: string | null;
  most_improved: { domain_name: string; score_delta: number; trust_score: number } | null;
}

export interface HistoryPoint {
  week_of: string;
  trust_score: number;
  /** True when the point was authored to give the demo a trend, not measured. */
  synthetic: boolean;
}

export interface ModelInfo {
  version: string;
  weights: Record<string, number>;
  tiers: { name: string; min_score: number }[];
  min_coverage: number;
  incident_threshold: number;
  quality_required: boolean;
  /** Passing checks needed for full quality marks. */
  breadth_target: number;
  /** Ceiling on quality when the only evidence is catalog tests. */
  tests_fallback_cap: number;
  freshness_window_days: number;
}

export async function getLeaderboard(): Promise<LeaderboardResponse> {
  const res = await fetch(`${API}/api/leaderboard`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load leaderboard");
  return res.json();
}

/**
 * The scoring model, fetched rather than restated here.
 *
 * The weights and cut-offs used to live in this file as well as in the Python,
 * which meant a change to the model silently made the dashboard's own legend
 * wrong while every number on the page kept looking plausible.
 */
export async function getModel(): Promise<ModelInfo> {
  const res = await fetch(`${API}/api/model`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load the scoring model");
  return res.json();
}

/**
 * Returns null when the domain is not scored, and throws when the API itself
 * fails. The caller needs to tell those apart: "this team does not exist" and
 * "the backend is down" are different messages for the reader.
 */
export async function getHistory(domain: string): Promise<HistoryPoint[] | null> {
  const res = await fetch(`${API}/api/domains/${encodeURIComponent(domain)}/history`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("Failed to load history");
  const data = await res.json();
  return data.history;
}

/** Correct English ordinals: 1st, 2nd, 3rd, 4th ... 21st, 22nd. */
export function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] ?? s[v] ?? s[0]);
}

export type Tier = "gold" | "silver" | "bronze" | "at-risk" | "unrated";

/**
 * Tier for a score, given the model's cut-offs.
 *
 * A team below the model's coverage floor is `unrated`, which is not a bad
 * grade: it means TrustBoard could not judge it. Rendering that as at-risk
 * would accuse a team of bad data on the strength of a gap in the catalog.
 */
export function tierOf(model: ModelInfo, score: number, rated: boolean): Tier {
  // No fallback table. A local copy of the cut-offs is how this file came to
  // state a model the scorer had stopped using, so the model is a required
  // argument and the only source.
  if (!rated) return "unrated";
  for (const t of model.tiers) {
    if (score >= t.min_score) return t.name as Tier;
  }
  return "at-risk";
}

/**
 * The component worth fixing first: weight times room to improve.
 *
 * The same rule the Python scorer applies. Picking the lowest raw value instead
 * would have this page and the scorecard TrustBoard writes into DataHub send a
 * team after two different signals for the same problem.
 */
export function highestLeverage(
  components: Record<string, number | null>,
  weights: Record<string, number>,
): { name: string; value: number } | null {
  const present = Object.entries(components).filter(
    ([name, v]) => v != null && weights[name] != null,
  ) as [string, number][];
  if (present.length === 0) return null;
  const [name, value] = present.reduce((a, b) =>
    weights[b[0]] * (100 - b[1]) > weights[a[0]] * (100 - a[1]) ? b : a,
  );
  return { name, value };
}

export interface NavigatorStep {
  tool: string;
  arg: string;
  result: string;
  /** search | pass | fail | write | done — drives the icon and the row tint. */
  kind: string;
}

export interface NavigatorRun {
  task: string;
  recorded_at: string;
  model: string;
  steps: NavigatorStep[];
  chosen: string;
  summary: string;
  rejected: { asset: string; why: string };
  incident: { title: string; state: string; body: string };
}

/**
 * A recorded run of the Navigator.
 *
 * Served as data rather than described in prose because the agent is the part of
 * this project a reader is most entitled to be sceptical about, and the list of
 * calls it actually made is the only answer to that.
 */
export async function getNavigatorRun(): Promise<NavigatorRun> {
  const res = await fetch(`${API}/api/navigator-run`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load the Navigator run");
  return res.json();
}
