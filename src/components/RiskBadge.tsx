import React from 'react';
import { PriorityLevel } from '../types';

interface RiskBadgeProps {
  level: PriorityLevel | string;
  size?: 'sm' | 'md' | 'lg';
  showDot?: boolean;
}

export const RiskBadge: React.FC<RiskBadgeProps> = ({
  level,
  size = 'md',
  showDot = true,
}) => {
  const getBadgeStyle = (lvl: string) => {
    switch (lvl) {
      case 'Immediate Relocation':
      case 'Critical':
        return {
          bg: 'bg-red-500/10 border-red-500/30 text-red-300',
          dot: 'bg-red-600',
          ring: 'ring-red-500/20',
        };
      case 'Short-Term Relocation':
      case 'High':
        return {
          bg: 'bg-amber-500/10 border-amber-500/30 text-amber-300',
          dot: 'bg-amber-600',
          ring: 'ring-amber-500/20',
        };
      case 'Medium-Term Relocation':
      case 'Medium':
        return {
          bg: 'bg-yellow-500/15 border-yellow-500/30 text-yellow-300',
          dot: 'bg-yellow-600',
          ring: 'ring-yellow-500/20',
        };
      case 'Monitor Only':
      case 'Low':
      default:
        return {
          bg: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300',
          dot: 'bg-emerald-600',
          ring: 'ring-emerald-500/20',
        };
    }
  };

  const style = getBadgeStyle(level);
  const sizeClasses =
    size === 'sm'
      ? 'text-xs px-2 py-0.5'
      : size === 'lg'
      ? 'text-sm px-3 py-1.5 font-semibold'
      : 'text-xs px-2.5 py-1 font-medium';

  return (
    <span
      id={`risk-badge-${level.replace(/\s+/g, '-').toLowerCase()}`}
      className={`inline-flex items-center gap-1.5 rounded-full border whitespace-nowrap ${style.bg} ${sizeClasses}`}
    >
      {showDot && (
        <span
          className={`h-1.5 w-1.5 rounded-full ${style.dot} animate-pulse`}
          aria-hidden="true"
        />
      )}
      <span>{level}</span>
    </span>
  );
};
