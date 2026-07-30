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
import {
  getHistory,
  getLeaderboard,
  getModel,
  ordinal,
  tierOf,
  type HistoryPoint,
  type ModelInfo,
  type Team,
} from "@/lib/api";

/** An unranked neighbour has no position to show; "0th" is not one. */
const rankLabel = (t: Team) => (t.rank_this_week ? `${ordinal(t.rank_this_week)} ` : "");

// The weight of each component comes from the API, next to the scores it
// produced, rather than being typed in again here where it can go stale.
const SIGNALS = [
  { key: "assertions_passing_pct", component: "quality", label: "Quality", Icon: SealCheck },
  { key: "documentation_score", component: "documentation", label: "Documentation", Icon: BookOpen },
  { key: "ownership_score", component: "ownership", label: "Ownership", Icon: UserCircle },
  { key: "freshness_score", component: "freshness", label: "Freshness", Icon: ClockCounterClockwise },
] as const;

/** The tier above the current one, and the score that reaches it. */
function nextTier(model: ModelInfo, tier: string) {
  const i = model.tiers.findIndex((t) => t.name === tier);
  if (i <= 0) return null;
  return { name: model.tiers[i - 1].name, at: model.tiers[i - 1].min_score };
}

function tierScale(model: ModelInfo) {
  return model.tiers
    .map((t, i) =>
      i === model.tiers.length - 1
        ? `${t.name.replace("-", " ")} below ${model.tiers[i - 1].min_score}`
        : `${t.name} ${t.min_score} and above`,
    )
    .join(", ");
}

// Only link to DataHub when a public instance is configured. A local instance
// is useless to anyone opening the deployed dashboard.
const DATAHUB_URL = process.env.NEXT_PUBLIC_DATAHUB_URL;

export default function DomainDetail({ params }: { params: { name: string } }) {
  const domain = decodeURIComponent(params.name);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [team, setTeam] = useState<Team | null>(null);
  const [model, setModel] = useState<ModelInfo | null>(null);
  const [neighbours, setNeighbours] = useState<{ prev: Team | null; next: Team | null }>({ prev: null, next: null });
  const [total, setTotal] = useState(0);
  const [state, setState] = useState<"loading" | "ready" | "notfound" | "error">("loading");

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([getHistory(domain), getLeaderboard(), getModel()])
      .then(([h, board, m]) => {
        if (controller.signal.aborted) return;
        setModel(m);
        const idx = board.teams.findIndex((t) => t.domain_name === domain);
        if (h === null && idx < 0) {
          setState("notfound");
          return;
        }
        setHistory(h ?? []);
        setTeam(idx >= 0 ? board.teams[idx] : null);
        setTotal(board.teams.length);
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

  if (state === "notfound" || !team || !model) {
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
  const tier = tierOf(model, score, team.rated !== false);
  const next = nextTier(model, tier);

  return (
    <main className="shell">
      {backLink}

      <header className={`detail__head tier-${tier}`}>
        <div>
          <h1>{domain}</h1>
          <p className="headline__sub">
            {team.rank_this_week
              ? `${ordinal(team.rank_this_week)} of ${total} teams`
              : "Not ranked this week"}
            {team.score_last_week != null && (
              <>
                {" · "}
                {score >= team.score_last_week ? "up" : "down"}{" "}
                {Math.abs(score - team.score_last_week).toFixed(1)} points since last week
              </>
            )}
            {DATAHUB_URL && team.domain_urn && (
              <>
                {" · "}
                <a
                  className="inline-link"
                  href={`${DATAHUB_URL}/domain/${encodeURIComponent(team.domain_urn)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open in DataHub <ArrowSquareOut size={12} weight="light" aria-hidden="true" />
                </a>
              </>
            )}
          </p>
        </div>
        {/* NumberFlow exposes one node per digit, so a screen reader spells the
            score out. The container carries the accessible name instead. */}
        <div
          className="detail__score tnum"
          role="img"
          aria-label={`Trust score ${score.toFixed(1)}, ${tier.replace("-", " ")} tier`}
          style={{ color: `var(--tier-${tier === "at-risk" ? "risk" : tier})` }}
        >
          <span aria-hidden="true">
            <NumberFlow value={Number(score.toFixed(1))} locales="en-US"
              format={{ minimumFractionDigits: 1, maximumFractionDigits: 1 }} />
          </span>
          <span className="detail__tier">{tier.replace("-", " ")} tier</span>
        </div>
      </header>

      <p className="next-tier">
        {tier === "unrated" ? (
          <>
            <b>Unrated.</b> Signal coverage was under{" "}
            {Math.round(model.min_coverage * 100)}%, too little to publish a score.{" "}
          </>
        ) : next ? (
          <>
            <b>{(next.at - score).toFixed(1)} points</b> to reach {next.name} tier.{" "}
          </>
        ) : (
          <>
            <b>Top tier.</b> Stay at {model.tiers[0].min_score} or above to hold{" "}
            {model.tiers[0].name}.{" "}
          </>
        )}
        <span className="next-tier__scale">Tiers: {tierScale(model)}.</span>
      </p>

      <section className="signals" aria-label="Score components">
        {SIGNALS.map((s, i) => {
          const value = team[s.key] as number | null;
          return (
            <div className="signal-cell" key={s.key}>
              <s.Icon size={17} weight="light" className="signal-cell__icon" aria-hidden="true" />
              <div className="signal-cell__value tnum" title={value == null ? "No signal collected. Its weight is redistributed across the other components." : undefined}>
                {value != null ? `${Math.round(value)}%` : "—"}
              </div>
              <div className="signal-cell__label">
                {s.label} · {Math.round((model.weights[s.component] ?? 0) * 100)}% of score
                {value == null && <span className="signal-cell__na"> · not measured</span>}
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

      <p className="signals__note">
        The team score averages its dataset scores, weighting each dataset by how many
        others read from it, and each dataset score is renormalized over the signals
        available for it. These four figures are plain averages per component, so they
        describe where the team stands on each rather than adding up to the score above.
        {team.signal_coverage != null && (
          <>
            {" "}
            Signal coverage this week was{" "}
            <b>{Math.round(team.signal_coverage * 100)}%</b>
            {team.dataset_count != null && <> across {team.dataset_count} datasets</>}
            {team.score_version && <>, scored by model v{team.score_version}</>}.
          </>
        )}
      </p>

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
            <Link
              href={`/domain/${encodeURIComponent(neighbours.prev.domain_name)}`}
              aria-label={`Ranked above: ${rankLabel(neighbours.prev)}${neighbours.prev.domain_name}`}
            >
              <ArrowLeft size={13} weight="light" aria-hidden="true" />
              {rankLabel(neighbours.prev)}{neighbours.prev.domain_name}
            </Link>
          ) : (
            <span />
          )}
          {neighbours.next && (
            <Link
              href={`/domain/${encodeURIComponent(neighbours.next.domain_name)}`}
              className="pager__next"
              aria-label={`Ranked below: ${rankLabel(neighbours.next)}${neighbours.next.domain_name}`}
            >
              {rankLabel(neighbours.next)}{neighbours.next.domain_name}
              <ArrowLeft size={13} weight="light" aria-hidden="true" style={{ transform: "rotate(180deg)" }} />
            </Link>
          )}
        </nav>
      )}
    </main>
  );
}
