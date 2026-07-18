/**
 * Row-level trend sparkline. Adds information density to each standings row
 * instead of leaving the width empty, and shows the shape of a team's season
 * at a glance.
 */
export function Sparkline({ points, tone }: { points: number[]; tone: "up" | "down" | "flat" }) {
  if (!points || points.length < 2) return <svg width="88" height="22" aria-hidden="true" />;

  const W = 88;
  const H = 22;
  const P = 3;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;

  const x = (i: number) => P + (i / (points.length - 1)) * (W - P * 2);
  const y = (v: number) => H - P - ((v - min) / span) * (H - P * 2);

  const d = points.map((v, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const stroke =
    tone === "up" ? "var(--signal)" : tone === "down" ? "var(--alert)" : "var(--text-faint)";

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true" style={{ overflow: "visible" }}>
      <path d={d} fill="none" stroke={stroke} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.85" />
      <circle cx={x(points.length - 1)} cy={y(points[points.length - 1])} r="2.2" fill={stroke} />
    </svg>
  );
}
