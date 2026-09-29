import React, { useId } from 'react';

export interface SafeMoveLogoProps {
  /** icon = mark only; compact = smaller mark + wordmark; full = mark + wordmark (default) */
  variant?: 'full' | 'compact' | 'icon';
  /** size of the svg mark in px (default 32) */
  size?: number;
  /** optional aria-label; a wordmark-less mark without one is hidden from AT */
  ariaLabel?: string;
  className?: string;
}

/**
 * Single SafeMove AI brand mark used across every portal (header, login,
 * loading screen, sidebar, mobile header, error states). One component, one
 * SVG — never duplicate the logo in any other file.
 */
export const SafeMoveLogo: React.FC<SafeMoveLogoProps> = ({
  variant = 'full',
  size = 32,
  ariaLabel,
  className,
}) => {
  const gradientId = `smg-${useId()}`;
  const showWordmark = variant !== 'icon';
  const hideFromA11y = variant === 'icon' && !ariaLabel;

  const mark = (
    <svg
      viewBox="0 0 48 48"
      width={size}
      height={size}
      className={showWordmark ? 'shrink-0' : undefined}
      role={hideFromA11y ? undefined : 'img'}
      aria-hidden={hideFromA11y || undefined}
      aria-label={hideFromA11y ? undefined : ariaLabel || 'SafeMove AI'}
      focusable="false"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#4ade80" />
          <stop offset="100%" stopColor="#16a34a" />
        </linearGradient>
      </defs>
      {/* Rounded hexagon / shield with flat top, green brand gradient */}
      <polygon
        points="24,2 43.05,13 43.05,35 24,46 4.95,35 4.95,13"
        fill={`url(#${gradientId})`}
        stroke="#0a0e14"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      {/* Relocation chevron: movement away from hazard */}
      <path
        d="M24 34 L24 16 M15 24 L24 15 L33 24"
        fill="none"
        stroke="#ffffff"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Locator dot — the destination, in the primary brand green */}
      <circle cx="24" cy="34" r="3.4" fill="#22c55e" stroke="#0a0e14" strokeWidth="1.4" />
    </svg>
  );

  if (!showWordmark) {
    return <span className={`inline-flex ${className ?? ''}`}>{mark}</span>;
  }

  return (
    <span
      className={`inline-flex items-center gap-2 ${className ?? ''}`}
      role="img"
      aria-label={ariaLabel || 'SafeMove AI'}
    >
      {mark}
      <span className="text-sm-text font-extrabold tracking-tight leading-none whitespace-nowrap">
        SafeMove AI
      </span>
    </span>
  );
};