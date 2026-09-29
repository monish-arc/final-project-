import React from 'react';
import {
  BookOpen,
  Calculator,
  Database,
  Layers,
  ShieldCheck,
  Cpu,
  GitBranch,
  History,
} from 'lucide-react';

export const DocsPage: React.FC = () => {
  return (
    <div id="system-docs-view" className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="bg-sm-panel p-5 rounded-xl border border-sm-border shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold uppercase tracking-wider text-indigo-300 bg-indigo-500/10 border border-indigo-500/30 px-2 py-0.5 rounded">
              MATHEMATICAL SPECIFICATIONS
            </span>
          </div>
          <h2 className="text-xl font-bold text-sm-text tracking-tight flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-indigo-400" />
            <span>SafeMove AI Decision-Support Formulas & Architecture</span>
          </h2>
          <p className="text-xs text-sm-muted mt-0.5">
            Transparent mathematical models, resource constraint formulations, and PostGIS schema standards
          </p>
        </div>
      </div>

      {/* Grid of Formulas */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Formula 1: Relocation Priority Score */}
        <div className="bg-sm-panel p-6 rounded-xl border border-sm-border shadow-sm space-y-3">
          <div className="flex items-center gap-2 text-red-400 font-bold text-sm">
            <Calculator className="w-4 h-4" />
            <span>1. Relocation Priority Index (RPI)</span>
          </div>
          <div className="p-3 bg-sm-bg text-sm-text rounded-lg font-mono text-xs border border-sm-border overflow-x-auto">
            Priority = 0.50 &times; Hazard + 0.30 &times; Vulnerability + 0.20 &times; History
          </div>
          <p className="text-xs text-sm-muted leading-relaxed">
            Combines dynamic environmental threats (landslide, flood, cloudburst), localized socio-economic vulnerability (population density, dependents, medical access), and historical recurrence to provide an unbiased ranking for DM priority orders.
          </p>
          <div className="text-[11px] text-sm-muted pt-2 border-t border-sm-border space-y-1">
            <div className="flex justify-between">
              <span className="font-semibold text-red-400">Immediate Relocation:</span>
              <span>Score &ge; 75.0</span>
            </div>
            <div className="flex justify-between">
              <span className="font-semibold text-amber-400">Short-Term Relocation:</span>
              <span>Score 50.0 &ndash; 74.9</span>
            </div>
            <div className="flex justify-between">
              <span className="font-semibold text-yellow-400">Medium-Term Relocation:</span>
              <span>Score 30.0 &ndash; 49.9</span>
            </div>
            <div className="flex justify-between">
              <span className="font-semibold text-emerald-400">Monitor Only:</span>
              <span>Score &lt; 30.0</span>
            </div>
          </div>
        </div>

        {/* Formula 2: Composite Hazard Score */}
        <div className="bg-sm-panel p-6 rounded-xl border border-sm-border shadow-sm space-y-3">
          <div className="flex items-center gap-2 text-amber-400 font-bold text-sm">
            <Layers className="w-4 h-4" />
            <span>2. Composite Hazard Score</span>
          </div>
          <div className="p-3 bg-sm-bg text-sm-text rounded-lg font-mono text-xs border border-sm-border overflow-x-auto">
            Hazard = 0.40 &times; Landslide + 0.30 &times; Flood + 0.20 &times; Rain + 0.10 &times; Frequency
          </div>
          <p className="text-xs text-sm-muted leading-relaxed">
            Synthesizes multi-hazard exposure calibrated for Himalayan terrain. Landslide risk receives highest weighting due to chronic valley wall subsidence along shear faults (e.g. Main Central Thrust in Chamoli).
          </p>
          <div className="text-[11px] text-sm-muted pt-2 border-t border-sm-border">
            <span>Calibrated with 20 historical Chamoli disaster events (2013 Kedarnath surge, 2021 Rishiganga burst, 2023 Joshimath subsidence).</span>
          </div>
        </div>

        {/* Formula 3: Relocation Site Suitability */}
        <div className="bg-sm-panel p-6 rounded-xl border border-sm-border shadow-sm space-y-3">
          <div className="flex items-center gap-2 text-emerald-400 font-bold text-sm">
            <ShieldCheck className="w-4 h-4" />
            <span>3. Relocation Site Suitability Index</span>
          </div>
          <div className="p-3 bg-sm-bg text-sm-text rounded-lg font-mono text-xs border border-sm-border overflow-x-auto">
            Suitability = 0.30 &times; LowHazard + 0.20 &times; FlatLand + 0.15 &times; Road + 0.15 &times; Water + 0.10 &times; Health + 0.10 &times; School
          </div>
          <p className="text-xs text-sm-muted leading-relaxed">
            Evaluates prospective rehabilitation enclaves. Mandates low multi-hazard score, stable gradient (&lt; 15&deg; slope), year-round road connectivity, and accessible social infrastructure within a 2 km buffer.
          </p>
        </div>

        {/* Formula 4: Multi-Resource Carrying Capacity */}
        <div className="bg-sm-panel p-6 rounded-xl border border-sm-border shadow-sm space-y-3">
          <div className="flex items-center gap-2 text-blue-400 font-bold text-sm">
            <Cpu className="w-4 h-4" />
            <span>4. Multi-Resource Carrying Capacity</span>
          </div>
          <div className="p-3 bg-sm-bg text-sm-text rounded-lg font-mono text-xs border border-sm-border overflow-x-auto">
            Capacity = Min(Land, Water, School, Health, Road)
          </div>
          <p className="text-xs text-sm-muted leading-relaxed">
            Adopts Liebig&apos;s Law of the Minimum: Total safe settlement capacity cannot exceed the most constrained resource pillar. Prevents overburdening mountain towns and ensures sustainable habitat creation.
          </p>
          <div className="text-[11px] text-sm-muted pt-2 border-t border-sm-border">
            <span>Identifies exact limiting bottleneck (e.g. Gauchar water network capacity: 550 families).</span>
          </div>
        </div>
      </div>

      {/* Tech Stack & Standards */}
      <div className="bg-sm-panel p-6 rounded-xl border border-sm-border shadow-sm space-y-4">
        <h3 className="text-sm font-bold text-sm-text flex items-center gap-2">
          <Database className="w-4 h-4 text-purple-400" />
          <span>System Architecture & Integration Topology</span>
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs">
          <div className="p-3 rounded-lg bg-sm-panel-2 border border-sm-border">
            <span className="font-bold text-sm-text block mb-1">Frontend Layer</span>
            <p className="text-sm-muted text-[11px]">
              React 19, TypeScript, Vite, Tailwind CSS, Leaflet GIS mapping with custom divIcons, and Recharts visualization.
            </p>
          </div>
          <div className="p-3 rounded-lg bg-sm-panel-2 border border-sm-border">
            <span className="font-bold text-sm-text block mb-1">Backend Microservice</span>
            <p className="text-sm-muted text-[11px]">
              Python FastAPI with Pydantic schema validation, JWT auth, RBAC permissions, and pure algorithmic risk engine.
            </p>
          </div>
          <div className="p-3 rounded-lg bg-sm-panel-2 border border-sm-border">
            <span className="font-bold text-sm-text block mb-1">Geospatial Database</span>
            <p className="text-sm-muted text-[11px]">
              PostgreSQL with PostGIS extension (`init.sql`), spatial GIST indexing, GeoJSON polygon geometries, and Alembic migrations.
            </p>
          </div>
        </div>
      </div>

      {/* Historical Rainfall (Kerala) Module */}
      <div id="docs-historical-rainfall" className="bg-sm-panel p-6 rounded-xl border border-violet-500/30 shadow-sm space-y-4">
        <h3 className="text-sm font-bold text-sm-text flex items-center gap-2">
          <History className="w-4 h-4 text-violet-400" />
          <span>5. Historical (Previous-Year) Rainfall Baseline — Kerala</span>
        </h3>
        <p className="text-xs text-sm-muted leading-relaxed">
          The historical module ingests a source-verified CSV of daily rainfall per Kerala
          district (expected columns: <code className="px-1 py-0.5 rounded bg-sm-panel-2 border border-sm-border font-mono">district, observation_date, rainfall_mm, source, source_reference, data_year</code>, optional{' '}
          <code className="px-1 py-0.5 rounded bg-sm-panel-2 border border-sm-border font-mono">hazard_type</code>) and computes a percentile
          baseline that the live season is compared against.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
          <div className="p-3 rounded-lg bg-violet-500/10 border border-violet-500/30 space-y-2">
            <span className="font-bold text-violet-300 block">Baseline Stats</span>
            <div className="p-2 bg-sm-bg text-sm-text rounded font-mono text-[11px] border border-sm-border overflow-x-auto">
              Avg = &Sigma;rainfall / n
              <br />P90, P95 = percentile(X, 0.90/0.95)
            </div>
            <p className="text-violet-300 text-[11px]">
              Percentiles require a minimum of 30 observations; quality grades: GOOD (all-year coverage) / LIMITED (&ge; 60%) / INSUFFICIENT.
            </p>
          </div>
          <div className="p-3 rounded-lg bg-violet-500/10 border border-violet-500/30 space-y-2">
            <span className="font-bold text-violet-300 block">Severity Comparison</span>
            <div className="p-2 bg-sm-bg text-sm-text rounded font-mono text-[11px] border border-sm-border overflow-x-auto">
              ratio = rainfall_mm / baseline_avg
              <br />&ge;1.2 Elevated · &ge;1.5 High · &ge;2.0 Extreme
            </div>
            <p className="text-violet-300 text-[11px]">
              Endpoint <code className="px-1 py-0.5 rounded bg-sm-bg font-mono">/api/historical/kerala/&#123;district&#125;/compare</code> returns severity vs the previous-year average.
            </p>
          </div>
        </div>

        <div className="pt-2 text-[11px] text-sm-muted border-t border-sm-border">
          <span>
            Import via{' '}
            <code className="px-1 py-0.5 rounded bg-sm-panel-2 border border-sm-border font-mono">python scripts/import_historical_data.py --dataset &lt;csv&gt; [--year 2025] [--dry-run]</code>{' '}
            from the backend directory. Zero fabrication: all surfaces read{' '}
            <span className="font-bold text-sm-text">HISTORICAL DATA SOURCE NOT CONFIGURED</span> until a
            source-documented dataset (India-WRIS / IMD Gridded / KSDMA) is loaded.
          </span>
        </div>
      </div>
    </div>
  );
};