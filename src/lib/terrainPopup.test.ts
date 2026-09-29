import { describe, it, expect } from 'vitest';
import {
  terrainPointPopupHtml,
  TERRAIN_SOURCE,
} from './terrainPopup';
import type { TerrainResponse } from '../types';

const point = (data_status: string, extra: Record<string, unknown> = {}): TerrainResponse =>
  ({ data_status, data_source: TERRAIN_SOURCE, ...extra }) as unknown as TerrainResponse;

describe('terrainPopup shared builder', () => {
  it('exports the canonical SRTM source label', () => {
    expect(TERRAIN_SOURCE).toContain('SRTM');
  });

  it('opens with a "Fetching terrain data…" loading state while in flight', () => {
    const html = terrainPointPopupHtml({ lat: 30.5574, lng: 79.5658, elevation: null, point: null });
    expect(html).toContain('Fetching terrain data');
    expect(html).toContain('Loading terrain');
  });

  it('shows the cached elevation immediately during loading', () => {
    const html = terrainPointPopupHtml({ lat: 30.5574, lng: 79.5658, elevation: 912, point: null });
    expect(html).toContain('912 m');
  });

  it('renders a bounded RETRYING note instead of a terminal error while a transient retry is in flight', () => {
    const html = terrainPointPopupHtml({ lat: 30.5574, lng: 79.5658, elevation: null, point: null, retrying: true });
    expect(html).toContain('Terrain provider is temporarily unavailable. Retrying');
    expect(html).not.toContain('TEMPORARILY UNAVAILABLE');
  });

  it('labels a coverage gap as NO_DATA, never as a provider outage', () => {
    const noData = point('UNAVAILABLE', { reason: 'NASA SRTMGL1 has no tile at this coordinate (out of coverage).' });
    const html = terrainPointPopupHtml({ lat: 30.5574, lng: 79.5658, elevation: null, point: noData });
    expect(html).toContain('No elevation data available for this coordinate.');
    expect(html).toContain('out of coverage');
  });

  it('renders a permanent provider error with the real reason after retries are exhausted', () => {
    const failed = point('UNAVAILABLE', { reason: 'NASA Earthdata unreachable or failed to serve the SRTM tile.' });
    const html = terrainPointPopupHtml({ lat: 30.5574, lng: 79.5658, elevation: null, point: failed });
    expect(html).toContain('Terrain provider is temporarily unavailable.');
    expect(html).toContain('NASA Earthdata unreachable');
  });

  it('renders LIVE elevation + slope for a resolved point', () => {
    const live = point('LIVE', {
      elevation_m: 912,
      slope_percent: 21.5,
      slope_degrees: 12.12,
      slope_category: 'MODERATE',
      elevation_change_m: 34,
      computed_at: '2026-01-01T00:00:00Z',
    });
    const html = terrainPointPopupHtml({ lat: 30.5574, lng: 79.5658, elevation: 910, point: live });
    expect(html).toContain('912 m');
    expect(html).toContain('21.5%');
    expect(html).toContain('LIVE');
  });
});