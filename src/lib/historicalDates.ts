import type { HistoricalAvailabilitySummary } from '../types';

export const MONTHS_SHORT = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];

export function monthShort(month: number): string {
  return MONTHS_SHORT[(month - 1 + 12) % 12] ?? '';
}

export function daysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

/** Number of completed months available for a year (12 for archived FULL
 *  years; `completed_through_month` for the unfolding current year; 0 when
 *  the year has no archive entry). */
export function completedMonthsFor(
  avail: HistoricalAvailabilitySummary[],
  year: number
): number {
  const entry = avail.find((a) => a.year === year);
  if (!entry) return 0;
  if (entry.status === 'FULL') return 12;
  return Math.max(0, Math.min(12, entry.completed_through_month ?? 0));
}

/** True when a (year, month, day) selection is a real, archived day. */
export function withinCompleted(
  year: number,
  month: number,
  day: number,
  completedMonths: number
): boolean {
  if (month > completedMonths) return false;
  return day >= 1 && day <= daysInMonth(year, month);
}

export function fmtDateLabel(year: number, month: number, day: number): string {
  return `${day} ${monthShort(month)} ${year}`;
}

/** Human caption like "2026 (Jan–Aug)" for the historical timeline. */
export function completedPeriodCaption(avail: HistoricalAvailabilitySummary[], year: number): string {
  const completed = completedMonthsFor(avail, year);
  if (completed >= 12) return `${year} (Jan–Dec)`;
  return completed > 0 ? `${year} (Jan–${monthShort(completed)})` : `${year} (no completed archive)`;
}