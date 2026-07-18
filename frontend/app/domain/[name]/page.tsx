"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getHistory, getLeaderboard, tierOf, type HistoryPoint, type Team } from "@/lib/api";

const COMP_LABELS: Record<string, string> = {
  assertions_passing_pct: "Quality",
  documentation_score: "Documentation",
  freshness_score: "Freshness",
};

export default function DomainDetail({ params }: { params: { name: string } }) {
  const domain = decodeURIComponent(params.name);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [team, setTeam] = useState<Team | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    Promise.all([getHistory(domain), getLeaderboard()])
      .then(([h, board]) => {
        setHistory(h);
        setTeam(board.teams.find((t) => t.domain_name === domain) ?? null);
      })
      .catch(() => setError(true));
  }, [domain]);

  if (error) {
    return (
      <main className="wrap">
        <Link href="/" className="back">← Back to the league</Link>
        <p style={{ color: "var(--text-dim)" }}>No data for this team.</p>
      </main>
    );
  }

  const current = team?.trust_score ?? history[history.length - 1]?.trust_score ?? 0;
  const tier = tierOf(current);

  return (
    <main className="wrap">
      <Link href="/" className="back">← Back to the league</Link>

      <div className="detail-head">
        <h1>{domain}</h1>
        <span className={`badge tier-${tier}`}>{tier.replace("-", " ")}</span>
      </div>
      <p style={{ color: "var(--text-dim)" }}>
        Current Trust Score <strong style={{ color: "var(--text)" }}>{current.toFixed(1)}</strong>
        {team?.rank_this_week ? ` · rank ${team.rank_this_week}` : ""}
      </p>

      {team && (
        <div className="components">
          {(["assertions_passing_pct", "documentation_score", "freshness_score"] as const).map((k) => (
            <div className="comp" key={k}>
              <div className="cval">{team[k] != null ? Math.round(team[k] as number) : "—"}</div>
              <div className="clabel">{COMP_LABELS[k]}</div>
            </div>
          ))}
          <div className="comp">
            <div className="cval">{team.rank_this_week ?? "—"}</div>
            <div className="clabel">League rank</div>
          </div>
        </div>
      )}

      <div className="chart-card">
        <div className="label" style={{ color: "var(--text-faint)", marginBottom: "1rem", fontSize: "0.72rem", letterSpacing: "0.16em", textTransform: "uppercase" }}>
          Trust Score trend
        </div>
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={history} margin={{ top: 8, right: 12, bottom: 8, left: -12 }}>
            <CartesianGrid stroke="#262d40" strokeDasharray="3 3" />
            <XAxis dataKey="week_of" stroke="#5a6178" fontSize={12} tickLine={false} />
            <YAxis domain={[0, 100]} stroke="#5a6178" fontSize={12} tickLine={false} />
            <Tooltip
              contentStyle={{
                background: "#141926",
                border: "1px solid #262d40",
                borderRadius: 8,
                color: "#eef2fb",
              }}
            />
            <Line
              type="monotone"
              dataKey="trust_score"
              stroke="#5b8cff"
              strokeWidth={2.5}
              dot={{ r: 4, fill: "#5b8cff" }}
              activeDot={{ r: 6 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </main>
  );
}
