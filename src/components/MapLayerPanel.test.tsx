import { describe, it, expect } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MapLayerPanel } from './MapLayerPanel';
import { DataSourceStatus } from './DataSourceStatus';

const baseProps = {
  basemap: 'street' as const,
  onBasemapChange: () => {},
  showRedZones: true,
  onRedZonesChange: () => {},
  hazardTypes: ['Land Subsidence', 'Flash Flood'],
  visibleHazardTypes: ['Land Subsidence', 'Flash Flood'],
  onHazardTypeChange: () => {},
  showHabitations: true,
  onHabitationsChange: () => {},
  showSites: true,
  onSitesChange: () => {},
  showInfra: true,
  onInfraChange: () => {},
  showRoute: true,
  onRouteChange: () => {},
  showFlood: false,
  onFloodChange: () => {},
  floodDataStatus: 'DEMO' as const,
  hasFloodData: true,
  showRainfall: false,
  onRainfallChange: () => {},
  hasRainfallData: true,
  rainfallDataStatus: 'LIVE' as const,
  priorityFilter: 'all',
  onPriorityFilterChange: () => {},
  onResetCenter: () => {},
  dataStatus: null,
};

describe('MapLayerPanel UI Component', () => {
  it('renders street, satellite and terrain basemap options', () => {
    const html = renderToStaticMarkup(<MapLayerPanel {...baseProps} />);
    expect(html).toContain('map-basemap-street');
    expect(html).toContain('map-basemap-satellite');
    expect(html).toContain('map-basemap-terrain');
    expect(html).not.toContain('map-basemap-hybrid');
  });

  it('marks the active basemap with highlight classes', () => {
    const html = renderToStaticMarkup(<MapLayerPanel {...baseProps} basemap="satellite" />);
    const active = html.match(/id="map-basemap-satellite"[^>]*/)?.[0] ?? '';
    expect(active).toContain('bg-sm-green');
  });

  it('renders hazard sub-toggles only when red zones shown', () => {
    const html = renderToStaticMarkup(<MapLayerPanel {...baseProps} />);
    expect(html).toContain('Land Subsidence');
    expect(html).toContain('Flash Flood');

    const hidden = renderToStaticMarkup(<MapLayerPanel {...baseProps} showRedZones={false} />);
    expect(hidden).not.toContain('Flash Flood');
  });

  it('renders flood forecast toggle labelled with demo status', () => {
    const html = renderToStaticMarkup(<MapLayerPanel {...baseProps} showFlood />);
    expect(html).toContain('map-flood-layer-toggle');
    expect(html).toContain('bg-amber-400');
  });

  it('renders live rainfall toggle labelled with GPM status', () => {
    const html = renderToStaticMarkup(<MapLayerPanel {...baseProps} showRainfall />);
    expect(html).toContain('map-rainfall-layer-toggle');
    expect(html).toContain('Live Rainfall');
    expect(html).toContain('bg-emerald-400');

    const off = renderToStaticMarkup(
      <MapLayerPanel {...baseProps} hasRainfallData={false} rainfallDataStatus="NOT CONFIGURED" />
    );
    expect(off).toContain('map-rainfall-layer-toggle');
  });

  it('renders all operation toggles', () => {
    const html = renderToStaticMarkup(<MapLayerPanel {...baseProps} />);
    expect(html).toContain('Habitations (Priority)');
    expect(html).toContain('Safe Relocation Enclaves');
    expect(html).toContain('Infrastructure');
    expect(html).toContain('Evacuation Route');
  });
});

describe('DataSourceStatus UI Component', () => {
  it('defaults to demo/not-configured summary when no layers passed', () => {
    const html = renderToStaticMarkup(<DataSourceStatus />);
    expect(html).toContain('gis-data-status-panel');
    expect(html).toContain('Data Source Status');
  });

  it('renders a live status summary when layers provided', () => {
    const html = renderToStaticMarkup(
      <DataSourceStatus
        layers={[
          { layer: 'satellite_tiles', status: 'LIVE', source: 'Esri World Imagery', updated_at: '—' },
        ]}
      />
    );
    expect(html).toContain('gis-data-status-panel');
    expect(html).toContain('All layers live');
  });
});