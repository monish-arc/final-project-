import { describe, it, expect } from 'vitest';
import {
  monthShort,
  daysInMonth,
  completedMonthsFor,
  withinCompleted,
  fmtDateLabel,
} from './historicalDates';
import type { HistoricalAvailabilitySummary } from '../types';

const avail: HistoricalAvailabilitySummary[] = [
  { year: 2024, completed_through_month: 12, status: 'FULL', label: '2024 (Jan–Dec)' },
  { year: 2025, completed_through_month: 12, status: 'FULL', label: '2025 (Jan–Dec)' },
  { year: 2026, completed_through_month: 8, status: 'COMPLETED', label: '2026 (Jan–Aug)' },
];

describe('historicalDates helpers', () => {
  it('maps month numbers to short names', () => {
    expect(monthShort(1)).toBe('Jan');
    expect(monthShort(8)).toBe('Aug');
    expect(monthShort(12)).toBe('Dec');
  });

  it('covers leap years when counting days', () => {
    expect(daysInMonth(2025, 2)).toBe(28);
    expect(daysInMonth(2024, 2)).toBe(29);
    expect(daysInMonth(2025, 8)).toBe(31);
  });

  it('reads completed months per year from availability', () => {
    expect(completedMonthsFor(avail, 2024)).toBe(12);
    expect(completedMonthsFor(avail, 2025)).toBe(12);
    expect(completedMonthsFor(avail, 2026)).toBe(8);
    expect(completedMonthsFor([], 2026)).toBe(0);
  });

  it('checks a selection lies within the completed window', () => {
    expect(withinCompleted(2026, 8, 1, completedMonthsFor(avail, 2026))).toBe(true);
    expect(withinCompleted(2026, 9, 1, completedMonthsFor(avail, 2026))).toBe(false);
    expect(withinCompleted(2026, 12, 31, completedMonthsFor(avail, 2026))).toBe(false);
    expect(withinCompleted(2025, 12, 31, completedMonthsFor(avail, 2025))).toBe(true);
  });

  it('formats a day label like 12 Aug 2025', () => {
    expect(fmtDateLabel(2025, 8, 12)).toBe('12 Aug 2025');
  });
});