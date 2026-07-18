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
import { getLeaderboard, ordinal, tierOf, type Team } from "@/lib/api";

export const dynamic = "force-dynamic";

const SCORE_PARTS = [
  { Icon: SealCheck, weight: "35%", label: "Data tests passing" },
  { Icon: BookOpen, weight: "25%", label: "Documentation and glossary coverage" },
  { Icon: UserCircle, weight: "20%", label: "Datasets with an assigned owner" },
  { Icon: ClockCounterClockwise, weight: "20%", label: "Lineage and update recency" },
];

const AGENTS = [
  { Icon: MagnifyingGlass, name: "Auditor", text: "Reads quality, docs, ownership and lineage from DataHub." },
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

function weakestOf(team: Team) {
  const parts = [
    ["tests", team.assertions_passing_pct],
    ["docs", team.documentation_score],
    ["ownership", team.ownership_score],
    ["freshness", team.freshness_score],
  ].filter(([, v]) => v != null) as [string, number][];
  if (parts.length === 0) return "No signals yet";
  const [name, value] = parts.reduce((a, b) => (b[1] < a[1] ? b : a));
  return `Weakest: ${name} ${Math.round(value)}%`;
}

export default async function Home() {
  let data;
  try {
    data = await getLeaderboard();
  } catch {
    return (
      <main className="shell">
        <p className="empty-note">
          <b>Standings unavailable.</b> The TrustBoard API did not respond. Retry in a moment.
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
  const leaderTier = tierOf(leader.trust_score);
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
        aria-label={`First place, ${leader.domain_name}, trust score ${leader.trust_score.toFixed(1)}, ${leaderTier.replace("-", " ")} tier`}
      >
        <div>
          <div className="headline__label">
            <Crown size={12} weight="light" aria-hidden="true" />
            1st · Team of the week
          </div>
          <div className="headline__team">{leader.domain_name}</div>
          <p className="headline__sub">
            {leader.rank_last_week === 1 ? "Holds the top spot again" : "Takes the top spot"}
            {quality != null ? `, with ${Math.round(quality)}% of data tests passing.` : "."}
            {most_improved && most_improved.domain_name !== leader.domain_name && (
              <> {most_improved.domain_name} climbed the most, up {most_improved.score_delta.toFixed(1)} points.</>
            )}
          </p>
        </div>
        <div className="headline__score tnum">
          {leader.trust_score.toFixed(1)}
          <span>{leaderTier.replace("-", " ")} tier</span>
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
          const tier = tierOf(team.trust_score);
          const delta = deltaOf(team);
          const position = team.rank_this_week ?? i + 2;
          return (
            <Link
              key={team.domain_name}
              href={`/domain/${encodeURIComponent(team.domain_name)}`}
              className={`row tier-${tier}`}
              style={{ "--i": Math.min(i, 7) } as React.CSSProperties}
              aria-label={`${ordinal(position)}, ${team.domain_name}, trust score ${team.trust_score.toFixed(1)}, ${delta.dir}${delta.label}, ${tier.replace("-", " ")} tier`}
            >
              <div className="row__rank tnum">{ordinal(position)}</div>
              <div>
                <div className="row__team">{team.domain_name}</div>
                <div className="row__datasets">{weakestOf(team)}</div>
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
            {SCORE_PARTS.map(({ Icon, weight, label }) => (
              <li key={label}>
                <Icon size={15} weight="light" aria-hidden="true" />
                <span className="legend__weight tnum">{weight}</span>
                <span>{label}</span>
              </li>
            ))}
          </ul>
          <p className="legend__note">
            Tiers: gold 80 and above, silver 60, bronze 40, at risk below 40. Missing signals are
            removed and the rest renormalized, so a gap shows as reduced coverage instead of a
            hidden zero.
          </p>
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
