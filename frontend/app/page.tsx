import Link from "next/link";
import { Logo } from "@/components/Logo";
import { Sparkline } from "@/components/Sparkline";
import { getLeaderboard, tierOf, type Team } from "@/lib/api";

export const dynamic = "force-dynamic";

const ORDINAL = ["1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th"];

function deltaOf(team: Team) {
  if (team.score_last_week == null) return { label: "new", cls: "delta-flat" };
  const diff = team.trust_score - team.score_last_week;
  if (Math.abs(diff) < 0.05) return { label: "level", cls: "delta-flat" };
  return {
    label: `${diff > 0 ? "+" : "−"}${Math.abs(diff).toFixed(1)}`,
    cls: diff > 0 ? "delta-up" : "delta-down",
  };
}

export default async function Home() {
  let data;
  try {
    data = await getLeaderboard();
  } catch {
    return (
      <main className="shell">
        <p className="empty-note">
          The TrustBoard API is unreachable. Start it with{" "}
          <code>uvicorn backend.main:app</code>.
        </p>
      </main>
    );
  }

  const { teams, most_improved } = data;
  if (teams.length === 0) {
    return (
      <main className="shell">
        <p className="empty-note">No scores recorded yet. Run the weekly cycle to populate the league.</p>
      </main>
    );
  }

  const [leader, ...rest] = teams;
  const leaderTier = tierOf(leader.trust_score);
  const week = leader.week_of;

  return (
    <main className="shell">
      <header className="masthead">
        <div>
          <div className="masthead__mark">
            <Logo size={26} />
            <span className="masthead__kicker">TrustBoard</span>
          </div>
          <h1>Data Trust League</h1>
        </div>
        <p className="masthead__meta">
          Week of <b>{week}</b>
          <br />
          Scored from DataHub signals and written back to the graph.
        </p>
      </header>

      <section className={`headline tier-${leaderTier}`} aria-label="Team of the week">
        <div>
          <div className="headline__label">Team of the week</div>
          <div className="headline__team">{leader.domain_name}</div>
          <p className="headline__sub">
            Leads on {leader.assertions_passing_pct != null ? `${Math.round(leader.assertions_passing_pct)}% passing checks` : "quality checks"} across{" "}
            {leader.rank_last_week === 1 ? "a second consecutive week" : "the standings"}.
            {most_improved && most_improved.domain_name !== leader.domain_name && (
              <> {most_improved.domain_name} is the week&apos;s biggest climber, up {most_improved.score_delta.toFixed(1)}.</>
            )}
          </p>
        </div>
        <div className="headline__score tnum">
          {leader.trust_score.toFixed(1)}
          <span>{leaderTier.replace("-", " ")}</span>
        </div>
      </section>

      <section className="standings" aria-label="Standings">
        <div className="standings__head">
          <span>Pos</span>
          <span>Team</span>
          <span>Form</span>
          <span>Score</span>
          <span>Week</span>
          <span>Tier</span>
        </div>

        {rest.map((team, i) => {
          const tier = tierOf(team.trust_score);
          const delta = deltaOf(team);
          return (
            <Link
              key={team.domain_name}
              href={`/domain/${encodeURIComponent(team.domain_name)}`}
              className={`row tier-${tier}`}
            >
              <div className="row__rank tnum">{ORDINAL[i + 1] ?? `${i + 2}th`}</div>
              <div>
                <div className="row__team">{team.domain_name}</div>
                <div className="row__datasets">
                  {team.documentation_score != null
                    ? `${Math.round(team.documentation_score)}% documented`
                    : "signals pending"}
                </div>
              </div>
              <div className="row__spark">
                <Sparkline
                  points={team.spark ?? []}
                  tone={delta.cls === "delta-up" ? "up" : delta.cls === "delta-down" ? "down" : "flat"}
                />
              </div>
              <div className="row__score tnum">{team.trust_score.toFixed(1)}</div>
              <div className={`row__delta tnum ${delta.cls}`}>{delta.label}</div>
              <div className="tier-tag">{tier.replace("-", " ")}</div>
            </Link>
          );
        })}
      </section>

      <footer className="colophon">
        <div>
          <h2>How the score works</h2>
          <dl>
            <dt>35%</dt>
            <dd>Quality, from passing data tests</dd>
            <dt>25%</dt>
            <dd>Documentation and glossary coverage</dd>
            <dt>20%</dt>
            <dd>Ownership</dd>
            <dt>20%</dt>
            <dd>Lineage freshness</dd>
          </dl>
        </div>
        <div>
          <h2>What happens after scoring</h2>
          <p>
            The Auditor reads the signals from DataHub. The Scribe writes each score back to the
            graph as a structured property, tags every dataset with its trust tier, and opens an
            incident on the assets dragging a team down. The Herald posts these standings to Slack.
            A separate agent can then ask DataHub whether a dataset is trustworthy before using it.
          </p>
        </div>
      </footer>
    </main>
  );
}
