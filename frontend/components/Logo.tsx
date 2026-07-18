/**
 * TrustBoard mark: three lineage nodes climbing inside the corner brackets of a
 * ledger. The top node is solid gold, the team leading the league. Reads as
 * DataHub's graph and as a standings table at the same time.
 */
export function Logo({ size = 30 }: { size?: number }) {
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
        strokeWidth="1.5"
        strokeLinecap="square"
        opacity="0.45"
      />
      <path d="M15 32 L23.5 25.5 L32.5 16" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="15" cy="32" r="2.5" fill="var(--bg)" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="23.5" cy="25.5" r="2.5" fill="var(--bg)" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="32.5" cy="16" r="3.4" fill="var(--tier-gold)" />
    </svg>
  );
}
