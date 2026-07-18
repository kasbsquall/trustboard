/**
 * TrustBoard mark: a governance shield whose interior is a three-step podium.
 * The three bars carry the tier materials (gold, silver, bronze), so the mark
 * speaks the same language as the standings table.
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
        d="M24 4 L41 10 V24.5 C41 34 33.5 41.5 24 44.5 C14.5 41.5 7 34 7 24.5 V10 Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        opacity="0.85"
      />
      <rect x="14.5" y="27" width="5" height="8.5" rx="0.5" fill="var(--tier-bronze)" />
      <rect x="21.5" y="21" width="5" height="14.5" rx="0.5" fill="var(--tier-gold)" />
      <rect x="28.5" y="24.5" width="5" height="11" rx="0.5" fill="var(--tier-silver)" />
    </svg>
  );
}
