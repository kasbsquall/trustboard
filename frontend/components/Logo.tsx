/**
 * TrustBoard mark: three lineage nodes climbing inside the corner brackets of a
 * ledger. The top node is solid gold, the team leading the league.
 *
 * The stroke width is derived from the rendered size instead of being fixed.
 * A fixed value breaks at both ends: below 1px the browser cannot paint a solid
 * line and the mark reads as washed-out grey, while at large sizes the same
 * value turns clumsy. The floor of 1.25px keeps the small sizes crisp.
 */
export function Logo({ size = 84 }: { size?: number }) {
  const strokePx = Math.max(1.25, size * 0.028);
  const stroke = (strokePx * 48) / size;
  const nodeRadius = 2.5;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      role="img"
      aria-label="TrustBoard"
    >
      <path
        d="M7 15 V7 H15 M33 7 H41 V15 M41 33 V41 H33 M15 41 H7 V33"
        stroke="currentColor"
        strokeWidth={stroke * 0.88}
        strokeLinecap="square"
        opacity="0.3"
      />
      <path d="M15 32 L23.5 25.5 L32.5 16" stroke="currentColor" strokeWidth={stroke} />
      <circle cx="15" cy="32" r={nodeRadius} fill="var(--bg)" stroke="currentColor" strokeWidth={stroke} />
      <circle cx="23.5" cy="25.5" r={nodeRadius} fill="var(--bg)" stroke="currentColor" strokeWidth={stroke} />
      <circle cx="32.5" cy="16" r="3.6" fill="var(--tier-gold)" />
    </svg>
  );
}
