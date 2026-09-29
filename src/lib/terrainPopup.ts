import type { TerrainResponse } from '../types';

// Canonical SRTM source label used on the terrain popup even when a point
// request fails — the terrain surface always comes from NASA SRTM here, and
// labelling the source is honest even when the latest sample is unavailable.
export const TERRAIN_SOURCE = 'NASA Earthdata SRTM (LP DAAC SRTMGL1 v003)';

function escapeHtml(value: string | number | null | undefined): string {
  if (value == null) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatComputedAt(value: string): string {
  if (!value.includes('T')) return value;
  return `${value.slice(0, 19).replace('T', ' ')} UTC`;
}

/** A real SRTM point payload (LIVE) or an honest failure state (UNAVAILABLE /
 *  NOT_CONFIGURED). The failure shape only carries the fields we render for a
 *  failed point — no fabricated elevation/slope. */
export interface TerrainPointUnavailable {
  data_status: 'UNAVAILABLE' | 'NOT_CONFIGURED';
  data_source?: string | null;
  dataset?: string | null;
  sample_count?: number | null;
  computed_at?: string | null;
  reason?: string | null;
  elevation_m?: number | null;
  slope_category?: string | null;
}

export interface TerrainPopupState {
  lat: number;
  lng: number;
  // Elevation from the grid cell / fast path shown instantly while the full
  // point payload is still in flight (never treated as permanent data).
  elevation: number | null;
  // null => the point request is still in flight (loading / retrying).
  point: TerrainResponse | TerrainPointUnavailable | null;
  // True while a transient provider failure is being retried by the client
  // (bounded, single retry). Renders "temporarily unavailable — retrying"
  // instead of a terminal error; the request is still live.
  retrying?: boolean;
}

// Progressive terrain popup markup. The state machine separates every honest
// outcome so a slow-but-working provider is never mislabelled:
//   LOADING           "Fetching terrain data…" (amber) — request in flight
//   RETRYING          "Terrain provider is temporarily unavailable. Retrying…"
//   SUCCESS           real values + LIVE status
//   NO_DATA           "No elevation data available for this coordinate."
//   PERMANENT_ERROR   "Terrain provider is temporarily unavailable." + reason
//   CANCELLED         honest note with the Cancelled reason
function isNoDataReason(reason: string | null | undefined): boolean {
  if (!reason) return false;
  const value = reason.toLowerCase();
  return (
    value.includes('no tile') ||
    value.includes('out of coverage') ||
    value.includes('no elevation data') ||
    value.includes('outside the india srtm data domain') ||
    value.includes('outside the india srtm domain')
  );
}

export function terrainPointPopupHtml({ lat, lng, elevation, point, retrying }: TerrainPopupState): string {
  const loading = point === null;
  const failed = !loading && (point.data_status === 'UNAVAILABLE' || point.data_status === 'NOT_CONFIGURED');
  const resolvedPoint = !loading && !failed ? (point as TerrainResponse) : null;

  const cancelled = failed && /^cancelled\./i.test(point?.reason ?? '');
  const noData = failed && !cancelled && isNoDataReason(point?.reason);

  const source = point?.data_source ?? TERRAIN_SOURCE;

  const rows: string[] = [];
  if (loading) {
    rows.push(
      elevation != null
        ? `<div>Elevation: <b>${elevation.toFixed(0)} m</b></div>`
        : `<div>Elevation: <span style="color:#92400e">Loading terrain…</span></div>`
    );
    rows.push(`<div>Slope: <span style="color:#92400e">Loading slope…</span></div>`);
  } else if (failed) {
    rows.push(
      elevation != null
        ? `<div>Elevation: <b>${elevation.toFixed(0)} m</b> <span style="color:#64748b">(grid cell)</span></div>`
        : `<div>Elevation: <span style="color:#b91c1c">Unavailable</span></div>`
    );
    rows.push(`<div>Slope: <span style="color:#b91c1c">Unavailable</span></div>`);
    rows.push(`<div>Relief (window): <span style="color:#b91c1c">Unavailable</span></div>`);
  } else {
    const el = resolvedPoint.elevation_m ?? elevation;
    rows.push(
      el != null
        ? `<div>Elevation: <b>${el.toFixed(0)} m</b></div>`
        : `<div>Elevation: <span style="color:#b91c1c">Unavailable</span></div>`
    );
    if (resolvedPoint.slope_percent != null) {
      const category = resolvedPoint.slope_category ? escapeHtml(resolvedPoint.slope_category.replace(/_/g, ' ').toLowerCase()) : '';
      const meta = [resolvedPoint.slope_degrees != null ? `${resolvedPoint.slope_degrees.toFixed(2)}°` : '', category].filter(Boolean).join(', ');
      rows.push(
        `<div>Slope: <b>${resolvedPoint.slope_percent.toFixed(1)}%</b>${meta ? ` <span style="color:#64748b">(${meta})</span>` : ''}</div>`
      );
    } else {
      rows.push(`<div>Slope: <span style="color:#b91c1c">Unavailable</span></div>`);
    }
    if (resolvedPoint.elevation_change_m != null) {
      rows.push(`<div>Relief (window): <b>${resolvedPoint.elevation_change_m.toFixed(0)} m</b></div>`);
    }
  }

  const meta: string[] = [];
  meta.push(`<div><span style="color:#64748b">Source:</span> <b>${escapeHtml(source)}</b></div>`);
  if (point?.dataset) meta.push(`<div><span style="color:#64748b">Dataset:</span> <b>${escapeHtml(point.dataset)}</b></div>`);
  if (point?.sample_count != null) meta.push(`<div><span style="color:#64748b">Samples:</span> ${point.sample_count}</div>`);
  if (point?.computed_at) meta.push(`<div><span style="color:#64748b">Computed:</span> ${escapeHtml(formatComputedAt(point.computed_at))}</div>`);

  let status: string;
  let color: string;
  if (loading && retrying) {
    status = 'Terrain provider is temporarily unavailable. Retrying…';
    color = '#b45309';
  } else if (loading) {
    status = 'Fetching terrain data…';
    color = '#92400e';
  } else if (!failed) {
    status = String(resolvedPoint?.data_status ?? 'UNKNOWN');
    color = resolvedPoint?.data_status === 'LIVE' ? '#166534' : '#b45309';
  } else if (cancelled) {
    status = 'TEMPORARILY UNAVAILABLE';
    color = '#b91c1c';
  } else if (noData) {
    status = 'No elevation data available for this coordinate.';
    color = '#92400e';
  } else {
    status = 'Terrain provider is temporarily unavailable.';
    color = '#b91c1c';
  }

  const reason =
    !loading && failed && point?.reason
      ? `<div style="color:#b91c1c;margin-top:4px">${escapeHtml(point.reason)}</div>`
      : '';

  return `<div style="min-width:190px;font-size:12px">
    <div style="font-weight:700;color:#0f172a">Terrain — ${lat.toFixed(4)}, ${lng.toFixed(4)}</div>
    <div style="margin:4px 0;color:#334155">${rows.join('')}</div>
    ${meta.join('')}
    <div style="font-size:10px;font-weight:700;color:${color};margin-top:2px">${status}</div>
    ${reason}
  </div>`;
}