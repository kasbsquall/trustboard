"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import NumberFlow from "@number-flow/react";
import { TrendChart } from "@/components/TrendChart";
import { getHistory, getLeaderboard, tierOf, type HistoryPoint, type Team } from "@/lib/api";

const SIGNALS = [
  { key: "assertions_passing_pct", label: "Quality", weight: "35%" },
  { key: "documentation_score", label: "Documentation", weight: "25%" },
  { key: "freshness_score", label: "Freshness", weight: "20%" },
] as const;

export default function DomainDetail({ params }: { params: { name: string } }) {
  const domain = decodeURIComponent(params.name);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [team, setTeam] = useState<Team | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    Promise.all([getHistory(domain), getLeaderboard()])
      .then(([h, board]) => {
        setHistory(h);
        setTeam(board.teams.find((t) => t.domain_name === domain) ?? null);
        setState("ready");
      })
      .catch(() => setState("error"));
  }, [domain]);

  if (state === "error") {
    return (
      <main className="shell">
        <Link href="/" className="back">Back to the league</Link>
        <p className="empty-note">No data recorded for this team.</p>
      </main>
    );
  }

  const score = team?.trust_score ?? history[history.length - 1]?.trust_score ?? 0;
  const tier = tierOf(score);

  return (
    <main className="shell">
      <Link href="/" className="back">Back to the league</Link>

      <header className={`detail__head tier-${tier}`}>
        <div>
          <h1>{domain}</h1>
          <p className="headline__sub">
            {team?.rank_this_week ? `Position ${team.rank_this_week} in the league` : "Unranked"}
            {team?.score_last_week != null && (
              <> · {score >= team.score_last_week ? "up" : "down"} {Math.abs(score - team.score_last_week).toFixed(1)} from last week</>
            )}
          </p>
        </div>
        <div className="detail__score tnum" style={{ color: `var(--tier-${tier === "at-risk" ? "risk" : tier})` }}>
          <NumberFlow
            value={Number(score.toFixed(1))}
            format={{ minimumFractionDigits: 1, maximumFractionDigits: 1 }}
          />
        </div>
      </header>

      <section className="signals" aria-label="Score components">
        {SIGNALS.map((s) => {
          const value = team ? (team[s.key] as number | null) : null;
          return (
            <div className="signal-cell" key={s.key}>
              <div className="signal-cell__value tnum">
                {value != null ? Math.round(value) : "—"}
              </div>
              <div className="signal-cell__label">
                {s.label} · {s.weight}
              </div>
              <div className="signal-cell__bar">
                <i style={{ transform: `scaleX(${value != null ? value / 100 : 0})` }} />
              </div>
            </div>
          );
        })}
        <div className="signal-cell">
          <div className="signal-cell__value tnum">{team?.rank_this_week ?? "—"}</div>
          <div className="signal-cell__label">League position</div>
          <div className="signal-cell__bar">
            <i style={{ transform: "scaleX(0)" }} />
          </div>
        </div>
      </section>

      <section className="chart-panel">
        <div className="chart-panel__label">Trust score, week by week</div>
        {state === "loading" ? (
          <p className="empty-note">Loading history…</p>
        ) : (
          <TrendChart points={history} />
        )}
      </section>
    </main>
  );
}
