import { describe, it, expect } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { HistoricalBaselineCard } from './HistoricalBaselineCard';
import { HistoricalDistrictPanel } from './HistoricalDistrictPanel';
import { DataSourceStatus } from './DataSourceStatus';
import { HistoricalAvailability, HistoricalBaseline, HistoricalDistrictSummary } from '../types';

const configuredBaseline: HistoricalBaseline = {
  district_id: 561,
  district: 'Kozhikode',
  data_year: 2025,
  total_rainfall_mm: 3200,
  average_rainfall_mm: 8.77,
  max_rainfall_mm: 310.5,
  min_rainfall_mm: 0,
  observation_count: 365,
  date_range: { first: '2025-01-01', last: '2025-12-31' },
  median_rainfall_mm: 4.2,
  p90_rainfall_mm: 28.4,
  p95_rainfall_mm: 41.2,
  quality: { grade: 'GOOD', coverage_percent: 100, reason: 'Full calendar-year coverage' },
  source: 'IMD Gridded',
  source_reference: 'IMD-RAIN-2025-KK',
  status: 'HISTORICAL',
  live_data_status: 'NOT CONFIGURED',
};

const summary: HistoricalDistrictSummary = {
  district_id: 561,
  district: 'Kozhikode',
  data_year: 2025,
  observation_count: 365,
  average_rainfall_mm: 8.77,
  max_rainfall_mm: 310.5,
  source: 'IMD Gridded',
  status: 'HISTORICAL',
  quality_grade: 'GOOD',
  latest_observations: [],
};

const availability: HistoricalAvailability = {
  state: { code: 32, name: 'Kerala' },
  dataset_year: 2025,
  years_available: [2025],
  total_records: 365,
  districts: [{ code: 561, name: 'Kozhikode', records: 365 }],
  last_import_at: '2025-09-14T00:00:00Z',
  live_data_status: 'NOT CONFIGURED',
  status: 'HISTORICAL',
};

describe('HistoricalBaselineCard UI Component', () => {
  it('shows the NOT CONFIGURED banner when no dataset is configured', () => {
    const html = renderToStaticMarkup(
      <HistoricalBaselineCard
        availability={null}
        summaries={[]}
        baseline={null}
        selectedDistrictId={null}
        onDistrictChange={() => {}}
      />
    );
    expect(html).toContain('historical-baseline-card');
    expect(html).toContain('HISTORICAL DATA SOURCE NOT CONFIGURED');
  });

  it('populates the district dropdown from the Kerala hierarchy', () => {
    const html = renderToStaticMarkup(
      <HistoricalBaselineCard
        availability={availability}
        summaries={[summary]}
        baseline={configuredBaseline}
        selectedDistrictId={561}
        onDistrictChange={() => {}}
      />
    );
    expect(html).toContain('historical-district-select');
    expect(html).toContain('Wayanad');
    expect(html).toContain('Thiruvananthapuram');
  });

  it('renders baseline stats with HISTORICAL badge when configured', () => {
    const html = renderToStaticMarkup(
      <HistoricalBaselineCard
        availability={availability}
        summaries={[summary]}
        baseline={configuredBaseline}
        selectedDistrictId={561}
        onDistrictChange={() => {}}
      />
    );
    expect(html).toContain('>HISTORICAL<');
    expect(html).toContain('8.8 mm');
    expect(html).toContain('365');
    expect(html).toContain('GOOD');
    expect(html).not.toContain('HISTORICAL DATA SOURCE NOT CONFIGURED');
  });
});

describe('HistoricalDistrictPanel UI Component', () => {
  it('renders NOT CONFIGURED state when no baseline exists', () => {
    const html = renderToStaticMarkup(
      <HistoricalDistrictPanel
        districtId={561}
        onDistrictChange={() => {}}
        baseline={null}
        summaries={[]}
        availability={null}
      />
    );
    expect(html).toContain('historical-district-panel');
    expect(html).toContain('historical-district-panel-select');
    expect(html).toContain('HISTORICAL DATA SOURCE NOT CONFIGURED');
  });

  it('renders configured baseline metrics with dataset provenance', () => {
    const html = renderToStaticMarkup(
      <HistoricalDistrictPanel
        districtId={561}
        onDistrictChange={() => {}}
        baseline={configuredBaseline}
        summaries={[summary]}
        availability={availability}
      />
    );
    expect(html).toContain('>HISTORICAL<');
    expect(html).toContain('P90 28.4');
    expect(html).toContain('IMD Gridded');
    expect(html).toContain('Dataset year 2025');
  });
});

describe('DataSourceStatus HISTORICAL layer', () => {
  it('flags the historical_data layer in the collapsed status summary', () => {
    const html = renderToStaticMarkup(
      <DataSourceStatus
        layers={[
          { layer: 'historical_data', status: 'HISTORICAL', source: 'India-WRIS', updated_at: '—' },
        ]}
      />
    );
    expect(html).toContain('gis-data-status-panel');
    expect(html).toContain('Data Source Status');
    expect(html).toContain('historical×1');
  });
});