const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
}

export async function getLeaderboard(): Promise<LeaderboardResponse> {
  const res = await fetch(`${API}/api/leaderboard`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load leaderboard");
  return res.json();
}

export async function getHistory(domain: string): Promise<HistoryPoint[]> {
  const res = await fetch(`${API}/api/domains/${encodeURIComponent(domain)}/history`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error("Failed to load history");
  const data = await res.json();
  return data.history;
}

export function tierOf(score: number): "gold" | "silver" | "bronze" | "at-risk" {
  if (score >= 80) return "gold";
  if (score >= 60) return "silver";
  if (score >= 40) return "bronze";
  return "at-risk";
}
