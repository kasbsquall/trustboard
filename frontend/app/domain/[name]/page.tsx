"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowSquareOut,
  BookOpen,
  ClockCounterClockwise,
  ListNumbers,
  SealCheck,
  UserCircle,
} from "@phosphor-icons/react";
import NumberFlow from "@number-flow/react";
import { TrendChart } from "@/components/TrendChart";
import { getHistory, getLeaderboard, ordinal, tierOf, type HistoryPoint, type Team } from "@/lib/api";

const SIGNALS = [
  { key: "assertions_passing_pct", label: "Quality", weight: "35% of score", Icon: SealCheck },
  { key: "documentation_score", label: "Documentation", weight: "25%", Icon: BookOpen },
  { key: "ownership_score", label: "Ownership", weight: "20%", Icon: UserCircle },
  { key: "freshness_score", label: "Freshness", weight: "20%", Icon: ClockCounterClockwise },
] as const;

const NEXT_TIER: Record<string, { name: string; at: number } | null> = {
  "at-risk": { name: "bronze", at: 40 },
  bronze: { name: "silver", at: 60 },
  silver: { name: "gold", at: 80 },
  gold: null,
};

export default function DomainDetail({ params }: { params: { name: string } }) {
  const domain = decodeURIComponent(params.name);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [team, setTeam] = useState<Team | null>(null);
  const [neighbours, setNeighbours] = useState<{ prev: Team | null; next: Team | null }>({ prev: null, next: null });
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([getHistory(domain), getLeaderboard()])
      .then(([h, board]) => {
        if (controller.signal.aborted) return;
        const idx = board.teams.findIndex((t) => t.domain_name === domain);
        setHistory(h);
        setTeam(idx >= 0 ? board.teams[idx] : null);
        setNeighbours({
          prev: idx > 0 ? board.teams[idx - 1] : null,
          next: idx >= 0 && idx < board.teams.length - 1 ? board.teams[idx + 1] : null,
        });
        setState("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setState("error");
      });
    return () => controller.abort();
  }, [domain]);

  const backLink = (
    <Link href="/" className="back">
      <ArrowLeft size={13} weight="light" aria-hidden="true" /> All teams
    </Link>
  );

  if (state === "loading") {
    return (
      <main className="shell" aria-busy="true">
        {backLink}
        <div className="skeleton skeleton--head" />
        <div className="skeleton skeleton--signals" />
        <div className="skeleton skeleton--chart" />
        <p className="sr-only">Loading team detail</p>
      </main>
    );
  }

  if (state === "error") {
    return (
      <main className="shell">
        {backLink}
        <p className="empty-note">
          <b>Could not load this team.</b> The TrustBoard API did not respond.
        </p>
      </main>
    );
  }

  if (!team) {
    return (
      <main className="shell">
        {backLink}
        <p className="empty-note">
          <b>Team not found.</b> No domain named &quot;{domain}&quot; is being scored.
        </p>
      </main>
    );
  }

  const score = team.trust_score;
  const tier = tierOf(score);
  const next = NEXT_TIER[tier];
  const total = neighbours.prev || neighbours.next ? undefined : undefined;

  return (
    <main className="shell">
      {backLink}

      <header className={`detail__head tier-${tier}`}>
        <div>
          <h1>{domain}</h1>
          <p className="headline__sub">
            {team.rank_this_week ? `${ordinal(team.rank_this_week)} in the league` : "Not ranked this week"}
            {team.score_last_week != null && (
              <>
                {" · "}
                {score >= team.score_last_week ? "up" : "down"}{" "}
                {Math.abs(score - team.score_last_week).toFixed(1)} points since last week
              </>
            )}
            {team.domain_urn && (
              <>
                {" · "}
                <a
                  className="inline-link"
                  href={`http://localhost:9002/domain/${encodeURIComponent(team.domain_urn)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open in DataHub <ArrowSquareOut size={12} weight="light" aria-hidden="true" />
                </a>
              </>
            )}
          </p>
        </div>
        <div
          className="detail__score tnum"
          style={{ color: `var(--tier-${tier === "at-risk" ? "risk" : tier})` }}
        >
          <NumberFlow value={Number(score.toFixed(1))} format={{ minimumFractionDigits: 1, maximumFractionDigits: 1 }} />
          <span className="detail__tier">{tier.replace("-", " ")} tier</span>
        </div>
      </header>

      {next && (
        <p className="next-tier">
          <b>{(next.at - score).toFixed(1)} points</b> to reach {next.name} tier.
        </p>
      )}

      <section className="signals" aria-label="Score components">
        {SIGNALS.map((s, i) => {
          const value = team[s.key] as number | null;
          return (
            <div className="signal-cell" key={s.key}>
              <s.Icon size={17} weight="light" className="signal-cell__icon" aria-hidden="true" />
              <div className="signal-cell__value tnum">{value != null ? Math.round(value) : "—"}</div>
              <div className="signal-cell__label">
                {s.label} · {s.weight}
              </div>
              <div className="signal-cell__bar">
                <i
                  style={{
                    transform: `scaleX(${value != null ? value / 100 : 0})`,
                    transitionDelay: `${120 + i * 70}ms`,
                  }}
                />
              </div>
            </div>
          );
        })}
      </section>

      <section className="chart-panel">
        <div className="chart-panel__label">Trust score by week</div>
        <TrendChart points={history} />
        <p className="sr-only">
          {history.map((h) => `Week of ${h.week_of}: ${h.trust_score.toFixed(1)}.`).join(" ")}
        </p>
      </section>

      {(neighbours.prev || neighbours.next) && (
        <nav className="pager" aria-label="Other teams">
          {neighbours.prev ? (
            <Link href={`/domain/${encodeURIComponent(neighbours.prev.domain_name)}`}>
              <ArrowLeft size={13} weight="light" aria-hidden="true" />
              {ordinal(neighbours.prev.rank_this_week ?? 0)} {neighbours.prev.domain_name}
            </Link>
          ) : (
            <span />
          )}
          {neighbours.next && (
            <Link href={`/domain/${encodeURIComponent(neighbours.next.domain_name)}`} className="pager__next">
              {ordinal(neighbours.next.rank_this_week ?? 0)} {neighbours.next.domain_name}
              <ArrowLeft size={13} weight="light" aria-hidden="true" style={{ transform: "rotate(180deg)" }} />
            </Link>
          )}
        </nav>
      )}
    </main>
  );
}
