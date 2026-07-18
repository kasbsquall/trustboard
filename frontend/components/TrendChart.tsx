"use client";

import type { HistoryPoint } from "@/lib/api";

/**
 * Trend chart drawn as plain SVG so it inherits the product's tokens and
 * typography instead of looking like a charting library bolted on top.
 */
export function TrendChart({ points }: { points: HistoryPoint[] }) {
  if (points.length < 2) {
    return <p className="empty-note">Not enough history yet to draw a trend.</p>;
  }

  const W = 900;
  const H = 260;
  const PAD = { top: 18, right: 16, bottom: 34, left: 34 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const x = (i: number) => PAD.left + (i / (points.length - 1)) * innerW;
  const y = (v: number) => PAD.top + innerH - (v / 100) * innerH;

  const line = points.map((p, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${y(p.trust_score)}`).join(" ");
  const area = `${line} L ${x(points.length - 1)} ${PAD.top + innerH} L ${x(0)} ${PAD.top + innerH} Z`;

  const last = points[points.length - 1];
  const first = points[0];
  const climbing = last.trust_score >= first.trust_score;
  const stroke = climbing ? "var(--signal)" : "var(--alert)";

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height="auto"
      role="img"
      aria-label={`Trust score trend from ${first.trust_score.toFixed(1)} to ${last.trust_score.toFixed(1)}`}
      style={{ display: "block", overflow: "visible" }}
    >
      <defs>
        <linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.16" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>

      {[0, 25, 50, 75, 100].map((v) => (
        <g key={v}>
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(v)}
            y2={y(v)}
            stroke="var(--surface-line)"
            strokeWidth="1"
          />
          <text
            x={PAD.left - 10}
            y={y(v)}
            textAnchor="end"
            dominantBaseline="middle"
            fill="var(--text-faint)"
            style={{ fontSize: 11, fontFamily: "var(--font-ui)", fontVariantNumeric: "tabular-nums" }}
          >
            {v}
          </text>
        </g>
      ))}

      <path d={area} fill="url(#trend-fill)" />
      <path d={line} fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />

      {points.map((p, i) => {
        const isLast = i === points.length - 1;
        return (
          <g key={p.week_of}>
            <circle
              cx={x(i)}
              cy={y(p.trust_score)}
              r={isLast ? 5 : 3}
              fill={isLast ? stroke : "var(--bg)"}
              stroke={stroke}
              strokeWidth="2"
            />
            <text
              x={x(i)}
              y={H - 12}
              textAnchor="middle"
              fill="var(--text-faint)"
              style={{ fontSize: 11, fontFamily: "var(--font-ui)", fontVariantNumeric: "tabular-nums" }}
            >
              {p.week_of.slice(5)}
            </text>
          </g>
        );
      })}

      <text
        x={x(points.length - 1)}
        y={y(last.trust_score) - 16}
        textAnchor="end"
        fill="var(--text)"
        style={{
          fontSize: 15,
          fontFamily: "var(--font-display)",
          fontWeight: 700,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {last.trust_score.toFixed(1)}
      </text>
    </svg>
  );
}
