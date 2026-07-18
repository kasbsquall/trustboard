import Link from "next/link";
import { getLeaderboard, tierOf, type Team } from "@/lib/api";

export const dynamic = "force-dynamic";

const RANK_LABEL = ["1st", "2nd", "3rd"];

function Delta({ team }: { team: Team }) {
  if (team.score_last_week == null) {
    return <div className="delta flat">new</div>;
  }
  const diff = team.trust_score - team.score_last_week;
  if (Math.abs(diff) < 0.05) return <div className="delta flat">steady</div>;
  const up = diff > 0;
  return (
    <div className={`delta ${up ? "up" : "down"}`}>
      {up ? "▲" : "▼"} {Math.abs(diff).toFixed(1)}
    </div>
  );
}

export default async function Home() {
  let data;
  try {
    data = await getLeaderboard();
  } catch {
    return (
      <main className="wrap">
        <p style={{ color: "var(--text-dim)" }}>
          Could not reach the TrustBoard API. Start the backend with{" "}
          <code>uvicorn backend.main:app</code>.
        </p>
      </main>
    );
  }

  const { teams, team_of_the_week, most_improved } = data;
  const week = teams[0]?.week_of;

  return (
    <main className="wrap">
      <header className="masthead">
        <div>
          <div className="kicker">TrustBoard</div>
          <h1>Data Trust League</h1>
        </div>
        <p className="sub">
          Weekly trust scores for every data team, computed from DataHub and written back to the
          graph. {week ? `Week of ${week}.` : ""}
        </p>
      </header>

      <section className="highlights">
        <div className="card">
          <div className="label">Team of the week</div>
          <div className="value">{team_of_the_week ?? "—"}</div>
          <div className="meta">Highest trust score across the org</div>
        </div>
        <div className="card">
          <div className="label">Most improved</div>
          <div className="value">{most_improved?.domain_name ?? "—"}</div>
          <div className="meta">
            {most_improved ? `+${most_improved.score_delta.toFixed(1)} points this week` : "No prior week yet"}
          </div>
        </div>
      </section>

      <section className="board">
        {teams.map((team, i) => {
          const tier = tierOf(team.trust_score);
          return (
            <Link
              key={team.domain_name}
              href={`/domain/${encodeURIComponent(team.domain_name)}`}
              className={`row tier-${tier} ${i === 0 ? "top" : ""}`}
            >
              <div className="rank">{RANK_LABEL[i] ?? `${i + 1}th`}</div>
              <div>
                <div className="team-name">{team.domain_name}</div>
                <div className="team-sub">{team.rank_this_week}º of the league</div>
              </div>
              <div className={`badge tier-${tier}`}>{tier.replace("-", " ")}</div>
              <div className="score">{team.trust_score.toFixed(1)}</div>
              <Delta team={team} />
            </Link>
          );
        })}
      </section>

      <p className="footnote">
        Trust Score combines four signals read from DataHub: quality (passing data tests),
        documentation, ownership and lineage freshness. Each week the Auditor computes it, the Scribe
        writes it back to the graph as a structured property, tier tag and incident, and the Herald
        posts this leaderboard to Slack.
      </p>
    </main>
  );
}
