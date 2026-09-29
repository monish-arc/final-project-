import { describe, it, expect } from 'vitest';
import { buildFocus, focusFromPoints } from './regionViewport';

describe('buildFocus', () => {
  it('creates a point focus with sensible zoom default and label', () => {
    const focus = buildFocus({ lat: 30.75, lng: 79.5, zoom: 14 }, 'Raini', 'hab-raini');
    expect(focus.lat).toBe(30.75);
    expect(focus.lng).toBe(79.5);
    expect(focus.zoom).toBe(14);
    expect(focus.label).toBe('Raini');
    expect(focus.habitationId).toBe('hab-raini');
    expect(focus.bounds).toBeUndefined();
    // key is stamped by the caller so repeat requests still re-fly
    expect(focus.key).toBe('');
  });

  it('defaults zoom when not provided', () => {
    const focus = buildFocus({ lat: 11, lng: 76 }, 'Kerala');
    expect(focus.zoom).toBe(10);
  });
});

describe('focusFromPoints', () => {
  it('returns null when no points are supplied', () => {
    expect(focusFromPoints([], { lat: 30.42, lng: 79.35, zoom: 10 }, 'Route')).toBeNull();
  });

  it('produces a bounds focus that encloses all route points', () => {
    const focus = focusFromPoints(
      [
        { latitude: 30.1, longitude: 79.4 },
        { latitude: 30.2, longitude: 79.6 },
      ],
      { lat: 30.42, lng: 79.35, zoom: 10 },
      'Evacuation Route'
    )!;
    expect(focus).not.toBeNull();
    expect(focus.label).toBe('Evacuation Route');
    expect(focus.bounds![0]).toBeCloseTo(30.1);
    expect(focus.bounds![1]).toBeCloseTo(79.4);
    expect(focus.bounds![2]).toBeCloseTo(30.2);
    expect(focus.bounds![3]).toBeCloseTo(79.6);
  });

  it('falls back to a high-zoom point focus for a single degenerate point', () => {
    const focus = focusFromPoints(
      [{ latitude: 30.5574, longitude: 79.5658 }],
      { lat: 30.42, lng: 79.35, zoom: 10 },
      'Single'
    )!;
    expect(focus.bounds).toBeUndefined();
    expect(focus.zoom).toBeGreaterThanOrEqual(14);
    expect(focus.lat).toBeCloseTo(30.5574);
  });
});