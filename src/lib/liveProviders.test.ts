import { describe, it, expect, beforeEach } from 'vitest';
import {
  LIVE_PROVIDER_TEMPLATES,
  getLiveProviders,
  saveLiveProvider,
  removeLiveProvider,
  enabledLiveProviders,
  liveProviderStatus,
  resetLiveProviderStore,
} from './liveProviders';

beforeEach(() => {
  resetLiveProviderStore();
});

describe('liveProviders store', () => {
  it('exposes the standard provider templates', () => {
    expect(LIVE_PROVIDER_TEMPLATES.map((t) => t.kind)).toEqual([
      'open-meteo',
      'ecmwf',
      'noaa',
      'nws',
      'other',
    ]);
  });

  it('starts empty and round-trips a saved provider', () => {
    expect(getLiveProviders()).toEqual([]);
    const cfg = {
      id: 'open-meteo',
      name: 'Open-Meteo',
      kind: 'open-meteo' as const,
      baseUrl: 'https://api.open-meteo.com/v1',
      note: 'Free, no key required',
    };
    saveLiveProvider(cfg);
    const saved = getLiveProviders();
    expect(saved).toHaveLength(1);
    expect(saved[0].id).toBe('open-meteo');
    expect(saved[0].enabled).toBe(false);
  });

  it('upserts by id instead of duplicating', () => {
    saveLiveProvider({ id: 'noaa', name: 'NOAA', kind: 'noaa' });
    saveLiveProvider({ id: 'noaa', name: 'NOAA NDFD', kind: 'noaa', baseUrl: 'x' });
    const saved = getLiveProviders();
    expect(saved).toHaveLength(1);
    expect(saved[0].name).toBe('NOAA NDFD');
  });

  it('never stores a provider as enabled, even if requested', () => {
    saveLiveProvider({ id: 'other', name: 'Custom', kind: 'other', enabled: true as never });
    expect(getLiveProviders()[0].enabled).toBe(false);
  });

  it('removes a provider by id', () => {
    saveLiveProvider({ id: 'open-meteo', name: 'Open-Meteo', kind: 'open-meteo' });
    saveLiveProvider({ id: 'noaa', name: 'NOAA', kind: 'noaa' });
    removeLiveProvider('open-meteo');
    expect(getLiveProviders().map((p) => p.id)).toEqual(['noaa']);
  });

  it('reports every provider as disabled and enabledLiveProviders is empty', () => {
    saveLiveProvider({ id: 'nws', name: 'NWS', kind: 'nws' });
    for (const p of getLiveProviders()) {
      expect(liveProviderStatus(p)).toBe('disabled');
    }
    expect(enabledLiveProviders(getLiveProviders())).toEqual([]);
  });
});