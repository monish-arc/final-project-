import React, { useState } from 'react';
import {
  FileDown,
  Printer,
  ShieldAlert,
  Building,
  CheckCircle2,
  Calendar,
  DollarSign,
  TrendingDown,
  Download,
  Share2,
} from 'lucide-react';
import { Habitation, RelocationSite, RelocationRecommendation } from '../types';

interface ReportsPageProps {
  habitations: Habitation[];
  relocationSites: RelocationSite[];
  recommendations: RelocationRecommendation[];
}

export const ReportsPage: React.FC<ReportsPageProps> = ({
  habitations,
  relocationSites,
  recommendations,
}) => {
  const [copied, setCopied] = useState(false);

  const immediateVillages = habitations.filter(
    (h) => h.priority_level === 'Immediate Relocation'
  );

  const totalImmediateHouseholds = immediateVillages.reduce((acc, h) => acc + h.households, 0);
  const totalImmediatePop = immediateVillages.reduce((acc, h) => acc + h.population, 0);

  // Approximate SDRF/NDRF financial rehabilitation estimate (₹15 Lakh per household relocation package)
  const estimatedPackageCr = ((totalImmediateHouseholds * 1500000) / 10000000).toFixed(1);

  const handlePrint = () => {
    window.print();
  };

  const handleExportCsv = () => {
    const headers = [
      'Rank',
      'Village Code',
      'Village Name',
      'Priority Level',
      'Priority Score',
      'Hazard Score',
      'Vulnerability Score',
      'Population',
      'Households',
      'Hospital Dist (km)',
      'Recommended Relocation Site',
      'Target Families',
      'Risk Reduction %',
    ];

    const rows = habitations
      .sort((a, b) => b.priority_score - a.priority_score)
      .map((h, index) => {
        const rec = recommendations.find((r) => r.habitation_id === h.id);
        return [
          index + 1,
          `"${h.village_code}"`,
          `"${h.village_name}"`,
          `"${h.priority_level}"`,
          h.priority_score,
          h.hazard_score,
          h.vulnerability_score,
          h.population,
          h.households,
          h.hospital_distance_km,
          `"${rec ? rec.relocation_site_name : 'Pending'}"`,
          rec ? rec.recommended_families : '-',
          rec ? `${rec.risk_reduction_percent}%` : '-',
        ].join(',');
      });

    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `SafeMove_Chamoli_Relocation_Directive_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleShare = () => {
    navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  return (
    <div id="executive-reports-view" className="space-y-6 animate-in fade-in duration-200">
      {/* Header & Export Actions */}
      <div className="bg-sm-panel p-5 rounded-xl border border-sm-border shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold uppercase tracking-wider text-sm-muted bg-sm-panel-2 border border-sm-border px-2 py-0.5 rounded">
              OFFICIAL GOVERNMENT DIRECTIVE
            </span>
          </div>
          <h2 className="text-xl font-bold text-sm-text tracking-tight flex items-center gap-2">
            <FileDown className="w-5 h-5 text-red-400" />
            <span>District Disaster Relocation Master Plan</span>
          </h2>
          <p className="text-xs text-sm-muted mt-0.5">
            Actionable rehabilitation brief prepared for District Magistrate (Chamoli) & State Disaster Management Authority (USDMA)
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={handleExportCsv}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-sm-panel-2 hover:bg-sm-panel-2/80 text-sm-text text-xs font-semibold border border-sm-border transition"
          >
            <Download className="w-4 h-4 text-sm-muted" />
            <span>Export CSV Dataset</span>
          </button>
          <button
            onClick={handlePrint}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-sm-green hover:bg-sm-green-hover text-slate-900 text-xs font-semibold shadow-sm transition"
          >
            <Printer className="w-4 h-4" />
            <span>Print Directive</span>
          </button>
        </div>
      </div>

      {/* Official Government Memorandum Header */}
      <div className="bg-sm-panel rounded-xl border border-sm-border shadow-sm p-8 space-y-6">
        {/* Memo Header */}
        <div className="border-b border-sm-border pb-6 text-center space-y-1">
          <span className="text-xs font-bold text-sm-muted tracking-widest uppercase">
            Government of Uttarakhand | Disaster Management Department
          </span>
          <h1 className="text-2xl font-black text-sm-text tracking-tight">
            COMPREHENSIVE RED-ZONE RELOCATION DIRECTIVE
          </h1>
          <p className="text-xs text-sm-muted font-mono">
            REF: USDMA/CHM-RELOC/2026/08-PILOT | Chamoli District Multi-Hazard Master Plan
          </p>
        </div>

        {/* Executive Summary Metrics */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-center">
            <span className="text-xs text-red-300 font-bold uppercase tracking-wider block">
              Immediate Critical Shift
            </span>
            <span className="text-3xl font-extrabold text-red-400 mt-1 block">
              {totalImmediatePop.toLocaleString()} Citizens
            </span>
            <span className="text-xs text-red-400">
              {totalImmediateHouseholds.toLocaleString()} families across 5 critical villages
            </span>
          </div>

          <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-center">
            <span className="text-xs text-emerald-300 font-bold uppercase tracking-wider block">
              Safe Enclave Allocation
            </span>
            <span className="text-3xl font-extrabold text-emerald-400 mt-1 block">
              4 Safe Sites
            </span>
            <span className="text-xs text-emerald-400">
              Gauchar, Gwaldam, Pokhari & Tharali Buffer Enclaves
            </span>
          </div>

          <div className="p-4 rounded-xl bg-blue-500/10 border border-blue-500/30 text-center">
            <span className="text-xs text-blue-300 font-bold uppercase tracking-wider block">
              Estimated Rehab Outlay
            </span>
            <span className="text-3xl font-extrabold text-blue-400 mt-1 block">
              ₹{estimatedPackageCr} Crores
            </span>
            <span className="text-xs text-blue-400">
              SDRF / Central Assistance norm @ ₹15L / family
            </span>
          </div>
        </div>

        {/* Executive Narrative */}
        <div className="space-y-3 text-xs text-sm-muted leading-relaxed border-t border-sm-border pt-5">
          <h3 className="text-sm font-bold text-sm-text">
            1. Statement of Urgency & Hazard Evaluation
          </h3>
          <p>
            Based on autonomous geospatial evaluation combining 20 historical extreme events, slope gradient models, satellite subsidence contours, and drainage network data, five habitations—<strong>Joshimath Ward Cluster (86.8)</strong>, <strong>Raini Gorge (87.2)</strong>, <strong>Tapovan Hydro Corridor (82.1)</strong>, <strong>Helang Ridge (76.8)</strong>, and <strong>Ghat Bazar (75.4)</strong>—exceed the critical threshold (&ge; 75.0 Priority Score) requiring immediate relocation.
          </p>
          <p>
            Without timely intervention, impending cloudburst seasons and progressive toe erosion along the Alaknanda and Rishiganga rivers will jeopardize {totalImmediatePop.toLocaleString()} residents and critical Himalayan transit infrastructure.
          </p>
        </div>

        {/* Phase Allocation Table */}
        <div className="space-y-3 border-t border-sm-border pt-5">
          <h3 className="text-sm font-bold text-sm-text">
            2. Phased Relocation & Infrastructure Deployment Matrix
          </h3>
          <div className="overflow-x-auto border border-sm-border rounded-lg">
            <table className="w-full text-left text-xs text-sm-muted">
              <thead className="bg-sm-panel-2 text-sm-muted font-semibold border-b border-sm-border">
                <tr>
                  <th className="p-3">Phase & Timeline</th>
                  <th className="p-3">Source Habitation</th>
                  <th className="p-3">Households</th>
                  <th className="p-3">Designated Safe Enclave</th>
                  <th className="p-3">Infrastructure Prerequisite</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-sm-border text-xs">
                <tr>
                  <td className="p-3 font-bold text-red-400">
                    Phase 1 (Months 1–3)
                  </td>
                  <td className="p-3">Raini Gorge & Joshimath Wards</td>
                  <td className="p-3 font-semibold">430 Families</td>
                  <td className="p-3 text-emerald-400 font-semibold">Gauchar Plateau Enclave</td>
                  <td className="p-3 text-sm-muted">Temporary prefab shelters + Water pipe augmentation</td>
                </tr>
                <tr>
                  <td className="p-3 font-bold text-amber-400">
                    Phase 2 (Months 4–6)
                  </td>
                  <td className="p-3">Tapovan & Helang Ridge</td>
                  <td className="p-3 font-semibold">220 Families</td>
                  <td className="p-3 text-emerald-400 font-semibold">Gwaldam Terrace Enclave</td>
                  <td className="p-3 text-sm-muted">Road culvert widening + 35-seat primary school wing</td>
                </tr>
                <tr>
                  <td className="p-3 font-bold text-yellow-400">
                    Phase 3 (Months 7–12)
                  </td>
                  <td className="p-3">Ghat Bazar & Buffer Zones</td>
                  <td className="p-3 font-semibold">180 Families</td>
                  <td className="p-3 text-emerald-400 font-semibold">Pokhari Safe Terrace</td>
                  <td className="p-3 text-sm-muted">Community health sub-center + livelihood sheds</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* Infrastructure Requirements Breakdown */}
        <div className="space-y-3 border-t border-sm-border pt-5 text-xs text-sm-muted">
          <h3 className="text-sm font-bold text-sm-text">
            3. Carrying-Capacity Bottleneck Mitigation Requirements
          </h3>
          <p className="text-sm-muted">
            Field calculations verify that safe sites possess ample raw land area, but social infrastructure must be pre-emptively reinforced before family transfers:
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="p-3 bg-sm-panel-2 rounded-lg border border-sm-border">
              <span className="font-bold text-sm-text block mb-1">
                Water Supply Augmentation:
              </span>
              <span>18.5 km gravity-fed transmission line connecting Gauchar to Pindar river supply springs.</span>
            </div>
            <div className="p-3 bg-sm-panel-2 rounded-lg border border-sm-border">
              <span className="font-bold text-sm-text block mb-1">
                Educational Seats Expansion:
              </span>
              <span>Additional classrooms across 3 government higher secondary schools in Gwaldam & Pokhari.</span>
            </div>
            <div className="p-3 bg-sm-panel-2 rounded-lg border border-sm-border">
              <span className="font-bold text-sm-text block mb-1">
                Emergency Health Infrastructure:
              </span>
              <span>Establishment of a 24/7 Level-2 Trauma & Maternal Care facility in Gauchar.</span>
            </div>
            <div className="p-3 bg-sm-panel-2 rounded-lg border border-sm-border">
              <span className="font-bold text-sm-text block mb-1">
                All-Weather Egress Corridors:
              </span>
              <span>Slope stabilization and dual-lane paving of Pokhari-Karanprayag link road.</span>
            </div>
          </div>
        </div>

        {/* Signatures */}
        <div className="border-t border-sm-border pt-8 flex flex-wrap items-center justify-between text-xs text-sm-muted gap-4">
          <div>
            <span className="block font-bold text-sm-text">Generated by SafeMove AI Engine</span>
            <span>Spatial Decision-Support System for Chamoli Pilot</span>
          </div>
          <div className="text-right">
            <span className="block font-semibold text-sm-muted">Approved for Submission to:</span>
            <span>District Disaster Management Authority (DDMA), Chamoli</span>
          </div>
        </div>
      </div>
    </div>
  );
};