import Link from "next/link";
import {
  ArrowUUpLeft,
  MagnifyingGlass,
  SealCheck,
  ShieldWarning,
  PencilSimpleLine,
  Flag,
  Warning,
} from "@phosphor-icons/react/dist/ssr";
import { getNavigatorRun } from "@/lib/api";

export const dynamic = "force-dynamic";

// One icon per kind of step, so the shape of the run reads before the words do:
// a column of searches, then checks, then the one that failed, then the write.
const MARK = {
  search: MagnifyingGlass,
  pass: SealCheck,
  fail: ShieldWarning,
  write: PencilSimpleLine,
  done: Flag,
} as const;

export default async function NavigatorPage() {
  let run;
  try {
    run = await getNavigatorRun();
  } catch {
    return (
      <main className="shell">
        <p className="empty-note">
          <b>No recorded run.</b> The Navigator writes one when it runs against a live DataHub.
        </p>
      </main>
    );
  }

  const searches = run.steps.filter((s) => s.kind === "search").length;
  const misses = run.steps.filter((s) => s.kind === "search" && s.result === "no matches").length;
  const checks = run.steps.filter((s) => s.kind === "pass" || s.kind === "fail").length;

  return (
    <main className="shell">
      <header className="masthead">
        <div>
          <Link href="/" className="backlink">
            <ArrowUUpLeft size={13} weight="light" aria-hidden="true" /> Standings
          </Link>
          <h1>The Navigator</h1>
          <p className="masthead__tagline">
            The one component here that reasons. Everything else is deterministic on purpose.
          </p>
        </div>
        <p className="masthead__meta">
          Recorded {run.recorded_at}
          <br />
          <span className="masthead__note">
            A saved run, like the standings. The incident it produced is real and sits in the
            DataHub instance it ran against.
          </span>
        </p>
      </header>

      <section className="nav-brief">
        <div className="nav-brief__label">It was given this and nothing else</div>
        <p className="nav-brief__task">{run.task}</p>
        <p className="nav-brief__note">
          No dataset URN. No shortlist. No expected answer. It made{" "}
          <b>{searches} searches</b>, {misses} of which returned nothing because the catalog does
          not use the words the task used, checked <b>{checks} candidates</b> over MCP, and
          decided.
        </p>
      </section>

      <section className="nav-trace" aria-label="What the agent did">
        <div className="nav-trace__head">
          <span>Step</span>
          <span>Call</span>
          <span>What came back</span>
        </div>
        {run.steps.map((step, i) => {
          const Icon = MARK[step.kind as keyof typeof MARK] ?? MagnifyingGlass;
          return (
            <div
              key={`${step.tool}-${i}`}
              className={`nav-step nav-step--${step.kind}`}
              style={{ "--i": Math.min(i, 12) } as React.CSSProperties}
            >
              <span className="nav-step__n tnum">{i + 1}</span>
              <span className="nav-step__call">
                <Icon size={14} weight="light" aria-hidden="true" />
                <code>{step.tool}</code>
                <span className="nav-step__arg">{step.arg}</span>
              </span>
              <span className="nav-step__result">{step.result}</span>
            </div>
          );
        })}
      </section>

      <section className="nav-outcome">
        <div className="nav-outcome__pick">
          <div className="nav-outcome__label">It chose</div>
          <code className="nav-outcome__urn">{run.chosen}</code>
          <p>{run.summary}</p>
        </div>

        <div className="nav-outcome__reject">
          <div className="nav-outcome__label">
            <Warning size={12} weight="light" aria-hidden="true" /> It turned down
          </div>
          <code className="nav-outcome__urn">{run.rejected.asset}</code>
          <p>{run.rejected.why}</p>
        </div>
      </section>

      <section className="nav-loop">
        <h2>And then it wrote that back into the catalog</h2>
        <p className="nav-loop__why">
          This is the half most agents skip. A refusal that only reaches a log file teaches nobody
          anything. This one lands on the dataset, so the team that owns it finds out that a piece
          of work did not get built on their data, and why.
        </p>
        <div className="nav-incident">
          <div className="nav-incident__bar">
            <span className="nav-incident__state">{run.incident.state}</span>
            <span className="nav-incident__where">incident in DataHub</span>
          </div>
          <div className="nav-incident__title">{run.incident.title}</div>
          <pre className="nav-incident__body">{run.incident.body}</pre>
        </div>
        <p className="nav-loop__close">
          TrustBoard computed a score and wrote it to the graph. A separate process read it back
          over MCP and made a decision. The decision returned to the graph. Graph to agent to
          graph.
        </p>
      </section>
    </main>
  );
}
