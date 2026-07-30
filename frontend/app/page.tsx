import Link from "next/link";
import {
  BookOpen,
  ClockCounterClockwise,
  Crown,
  Megaphone,
  MagnifyingGlass,
  PencilSimpleLine,
  SealCheck,
  ShieldCheck,
  TrendDown,
  TrendUp,
  UserCircle,
} from "@phosphor-icons/react/dist/ssr";
import { Logo } from "@/components/Logo";
import { Sparkline } from "@/components/Sparkline";
import {
  getLeaderboard,
  getModel,
  highestLeverage,
  ordinal,
  tierOf,
  type ModelInfo,
  type Team,
} from "@/lib/api";

export const dynamic = "force-dynamic";

// One canonical name per component, matching the team detail page. The weight
// is not written here: it comes from the API with the scores, so the legend
// cannot drift away from the model that produced the numbers above it.
const SCORE_PARTS = [
  { Icon: SealCheck, key: "quality", name: "Quality", label: "data assertions passing, else catalog tests" },
  { Icon: BookOpen, key: "documentation", name: "Documentation", label: "descriptions and glossary coverage" },
  { Icon: UserCircle, key: "ownership", name: "Ownership", label: "datasets with an assigned owner" },
  { Icon: ClockCounterClockwise, key: "freshness", name: "Freshness", label: "how recently the data itself changed" },
];

const AGENTS = [
  { Icon: MagnifyingGlass, name: "Auditor", text: "Reads quality, docs, ownership and update recency from DataHub." },
  { Icon: PencilSimpleLine, name: "Scribe", text: "Writes the score back as a structured property, tags every dataset, and opens incidents on the ones dragging the team down." },
  { Icon: Megaphone, name: "Herald", text: "Posts these standings to Slack every week." },
  { Icon: ShieldCheck, name: "Gatekeeper", text: "A separate agent that asks DataHub whether a dataset is trustworthy before building on it." },
];

function deltaOf(team: Team) {
  if (team.score_last_week == null) return { label: "First week", cls: "delta-flat", dir: "" };
  const diff = team.trust_score - team.score_last_week;
  if (Math.abs(diff) < 0.05) return { label: "No change", cls: "delta-flat", dir: "" };
  return {
    label: `${diff > 0 ? "+" : "−"}${Math.abs(diff).toFixed(1)}`,
    cls: diff > 0 ? "delta-up" : "delta-down",
    dir: diff > 0 ? "up " : "down ",
  };
}

function componentsOf(team: Team): Record<string, number | null> {
  return {
    quality: team.assertions_passing_pct,
    documentation: team.documentation_score,
    ownership: team.ownership_score,
    freshness: team.freshness_score,
  };
}

function subtitleOf(team: Team, model: ModelInfo) {
  const best = highestLeverage(componentsOf(team), model.weights);
  const coverage =
    team.signal_coverage != null ? ` · ${Math.round(team.signal_coverage * 100)}% signal coverage` : "";
  if (!best) return `No signals yet${coverage}`;
  return `Fix first: ${best.name[0].toUpperCase()}${best.name.slice(1)} ${Math.round(best.value)}%${coverage}`;
}

export default async function Home() {
  let data;
  let model: ModelInfo;
  try {
    [data, model] = await Promise.all([getLeaderboard(), getModel()]);
  } catch {
    return (
      <main className="shell">
        <p className="empty-note">
          <b>Standings unavailable.</b> The TrustBoard API did not respond. Reload the page
          once it is back.
        </p>
      </main>
    );
  }

  const { teams, most_improved } = data;
  if (teams.length === 0) {
    return (
      <main className="shell">
        <p className="empty-note">
          <b>No standings yet.</b> The first table appears after the Auditor completes a run.
        </p>
      </main>
    );
  }

  const leader = teams[0];
  const leaderTier = tierOf(model, leader.trust_score, leader.rated !== false);
  const leaderDelta = deltaOf(leader);
  const quality = leader.assertions_passing_pct;

  return (
    <main className="shell">
      <header className="masthead">
        <div className="masthead__lockup">
          <Logo size={84} />
          <div>
            <h1>TrustBoard</h1>
            <p className="masthead__tagline">
              The weekly trust league for data teams
            </p>
          </div>
        </div>
        <p className="masthead__meta">
          Week of <b>{leader.week_of}</b>
          <br />
          Every score is read from DataHub and written back as metadata.
        </p>
      </header>

      <Link
        href={`/domain/${encodeURIComponent(leader.domain_name)}`}
        className={`headline tier-${leaderTier}`}
        aria-label={`First place, ${leader.domain_name}, trust score ${leader.trust_score.toFixed(1)}, ${leaderDelta.dir}${leaderDelta.label} points, ${leaderTier.replace("-", " ")} tier`}
      >
        <div>
          <div className="headline__label">
            <Crown size={12} weight="light" aria-hidden="true" />
            1st · Team of the week
          </div>
          <div className="headline__team">{leader.domain_name}</div>
          <p className="headline__sub">
            {leader.rank_last_week === 1 ? "Holds the top spot again" : "Takes the top spot"}
            {/* "quality checks", not "data tests". The quality signal comes from
                data assertions where a dataset has them and from catalog tests
                where it does not, so naming one of the two would be wrong on
                most of the datasets behind this number. */}
            {quality != null ? `, with ${Math.round(quality)}% of quality checks passing` : ""}
            {leader.signal_coverage != null
              ? ` at ${Math.round(leader.signal_coverage * 100)}% signal coverage.`
              : "."}
            {most_improved && most_improved.domain_name !== leader.domain_name && (
              <> {most_improved.domain_name} climbed the most, up {most_improved.score_delta.toFixed(1)} points.</>
            )}
          </p>
        </div>
        <div className="headline__score tnum">
          {leader.trust_score.toFixed(1)}
          <span>{leaderTier.replace("-", " ")} tier</span>
          {/* The table below promises a trend and a change for every team. The
              leader has to honour that too, or the rule breaks on the one row
              the reader looks at first. */}
          <div className="headline__trend" aria-hidden="true">
            <Sparkline points={leader.spark ?? []} tone={leaderDelta.cls === "delta-up" ? "up" : leaderDelta.cls === "delta-down" ? "down" : "flat"} />
            <span className={`tnum ${leaderDelta.cls}`}>
              {leaderDelta.cls === "delta-up" && <TrendUp size={13} weight="light" />}
              {leaderDelta.cls === "delta-down" && <TrendDown size={13} weight="light" />}
              {leaderDelta.label}
            </span>
          </div>
        </div>
      </Link>

      <section className="standings" aria-label="Standings">
        <div className="standings__head">
          <span>Rank</span>
          <span>Team</span>
          <span>Trend</span>
          <span>Score</span>
          <span>Change</span>
          <span>Tier</span>
        </div>

        {teams.slice(1).map((team, i) => {
          const tier = tierOf(model, team.trust_score, team.rated !== false);
          const delta = deltaOf(team);
          const position = team.rank_this_week ?? i + 2;
          return (
            <Link
              key={team.domain_name}
              href={`/domain/${encodeURIComponent(team.domain_name)}`}
              className={`row tier-${tier}`}
              style={{ "--i": Math.min(i, 7) } as React.CSSProperties}
              aria-label={`${ordinal(position)}, ${team.domain_name}, trust score ${team.trust_score.toFixed(1)}, ${delta.dir}${delta.label} points, ${tier.replace("-", " ")} tier`}
            >
              <div className="row__rank tnum">{ordinal(position)}</div>
              <div>
                <div className="row__team">{team.domain_name}</div>
                <div className="row__datasets">{subtitleOf(team, model)}</div>
              </div>
              <div className="row__spark">
                <Sparkline
                  points={team.spark ?? []}
                  tone={delta.cls === "delta-up" ? "up" : delta.cls === "delta-down" ? "down" : "flat"}
                />
              </div>
              <div className="row__score tnum">{team.trust_score.toFixed(1)}</div>
              <div className={`row__delta tnum ${delta.cls}`}>
                {delta.cls === "delta-up" && <TrendUp size={13} weight="light" aria-hidden="true" />}
                {delta.cls === "delta-down" && <TrendDown size={13} weight="light" aria-hidden="true" />}
                {delta.label}
              </div>
              <div className="tier-tag">{tier.replace("-", " ")}</div>
            </Link>
          );
        })}
      </section>

      <footer className="colophon">
        <div>
          <h2>How the score works</h2>
          <ul className="legend">
            {SCORE_PARTS.map(({ Icon, key, name, label }) => (
              <li key={name}>
                <Icon size={15} weight="light" aria-hidden="true" />
                <span className="legend__weight tnum">
                  {Math.round((model.weights[key] ?? 0) * 100)}%
                </span>
                <span>
                  <b>{name}</b> {label}
                </span>
              </li>
            ))}
          </ul>
          <p className="legend__note">
            Tiers:{" "}
            {model.tiers
              .map((t, i) =>
                i === model.tiers.length - 1
                  ? `${t.name.replace("-", " ")} below ${model.tiers[i - 1].min_score}`
                  : `${t.name} ${t.min_score} and above`,
              )
              .join(", ")}
            . Missing signals are removed and the rest renormalized, so a gap shows as reduced
            coverage instead of a hidden zero.{" "}
            {model.quality_required
              ? "A dataset with no quality signal at all is left unrated, whatever its coverage: there is no honest trust score for data nobody checks. "
              : ""}
            Below {Math.round(model.min_coverage * 100)}% coverage a team is left unrated rather
            than scored, and an incident opens below {model.incident_threshold}. Model v
            {model.version}.
          </p>
          {/* The earlier weeks of the trend were authored to give the demo a
              story. Saying so next to the chart costs a sentence and is the
              difference between a demo and a claim. */}
          {teams.some((t) => t.synthetic) ? null : (
            <p className="legend__note">
              This week is a real audit. The three earlier weeks in each trend were authored for
              the demo, not measured.
            </p>
          )}
        </div>
        <div>
          <h2>The agents behind it</h2>
          <ul className="legend legend--cycle">
            {AGENTS.map(({ Icon, name, text }) => (
              <li key={name}>
                <Icon size={15} weight="light" aria-hidden="true" />
                <span>
                  <b>{name}</b> {text}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </footer>
    </main>
  );
}
