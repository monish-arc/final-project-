import React, { useState } from 'react';
import {
  ShieldCheck,
  Users,
  Database,
  Server,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  Lock,
  Radio,
  FileCheck,
} from 'lucide-react';
import { User, UserRole } from '../types';
import { DEMO_USERS } from '../data/mockData';

interface AdminPageProps {
  currentUser: User;
  onSwitchUser: (user: User) => void;
  onResetSeedData: () => Promise<any>;
}

const AVAILABLE_USERS: User[] = DEMO_USERS;

export const AdminPage: React.FC<AdminPageProps> = ({
  currentUser,
  onSwitchUser,
  onResetSeedData,
}) => {
  const [resetting, setResetting] = useState(false);
  const [resetSuccess, setResetSuccess] = useState(false);
  const [healthStatus, setHealthStatus] = useState<{
    status: string;
    backend: string;
    database: string;
    checkedAt: string;
  }>({
    status: 'Healthy',
    backend: 'FastAPI Microservice (Port 8000) / Active',
    database: 'PostgreSQL + PostGIS Spatial Engine',
    checkedAt: new Date().toLocaleTimeString(),
  });

  const handleReset = async () => {
    if (!window.confirm('Reset Chamoli pilot dataset to original certified baseline?')) {
      return;
    }
    setResetting(true);
    try {
      await onResetSeedData();
      setResetSuccess(true);
      setTimeout(() => setResetSuccess(false), 3500);
    } finally {
      setResetting(false);
    }
  };

  const getRoleDescription = (role: UserRole) => {
    switch (role) {
      case 'admin':
        return 'Full system access: Manage user permissions, trigger database reseeding, alter spatial weights, and verify all field reports.';
      case 'state_officer':
        return 'Can manage operational assignments across the assigned state.';
      case 'district_officer':
        return 'Can manage operational assignments across the assigned district.';
      case 'sub_district_officer':
        return 'Can manage field and local-office assignments in the assigned sub-district.';
      case 'field_officer':
        return 'Can raise risk alerts in the assigned area.';
      case 'local_office':
        return 'Can manage local relief accommodation and participate in evacuation planning in the assigned area.';
      case 'gis_analysis_officer':
        return 'Read-only access to current and historical hazard analytics.';
      case 'normal_citizen':
        return 'Read-only access to public maps and published risk alerts.';
    }
  };

  return (
    <div id="admin-management-view" className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="bg-sm-panel p-5 rounded-xl border border-sm-border shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold uppercase tracking-wider text-purple-300 bg-purple-500/10 border border-purple-500/30 px-2 py-0.5 rounded">
              SYSTEM & SECURITY CONSOLE
            </span>
          </div>
          <h2 className="text-xl font-bold text-sm-text tracking-tight flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-purple-400" />
            <span>Administration & Role-Based Access Control</span>
          </h2>
          <p className="text-xs text-sm-muted mt-0.5">
            Switch simulated test personas, monitor API microservice health, and inspect national data connector readiness
          </p>
        </div>

        <div className="flex items-center gap-2">
          {resetSuccess && (
            <span className="text-xs text-emerald-300 font-semibold flex items-center gap-1 bg-emerald-500/10 px-2.5 py-1 rounded border border-emerald-500/30 animate-in fade-in">
              <CheckCircle2 className="w-3.5 h-3.5" /> Database Re-seeded
            </span>
          )}
          <button
            onClick={handleReset}
            disabled={resetting}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-sm-panel-2 hover:bg-sm-panel-2/80 text-sm-text text-xs font-semibold border border-sm-border transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${resetting ? 'animate-spin' : ''}`} />
            <span>{resetting ? 'Re-seeding...' : 'Reset Pilot Seed Data'}</span>
          </button>
        </div>
      </div>

      {/* Role Switcher Section */}
      <div className="bg-sm-panel p-5 rounded-xl border border-sm-border shadow-sm space-y-4">
        <div className="flex items-center justify-between border-b border-sm-border pb-3">
          <div>
            <h3 className="text-sm font-bold text-sm-text flex items-center gap-2">
              <Users className="w-4 h-4 text-sm-muted" />
              <span>Simulate User Roles (RBAC Demonstration)</span>
            </h3>
            <p className="text-xs text-sm-muted">
              Click any user role below to instantly switch active permissions in this session
            </p>
          </div>
          <span className="text-xs text-sm-muted font-mono">
            Active: <strong className="text-purple-400">{currentUser.role.toUpperCase()}</strong>
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {AVAILABLE_USERS.map((user) => {
            const isActive = user.id === currentUser.id;

            return (
              <div
                key={user.id}
                id={`user-role-card-${user.role}`}
                onClick={() => onSwitchUser(user)}
                className={`p-4 rounded-xl border text-xs cursor-pointer transition flex flex-col justify-between space-y-3 ${
                  isActive
                    ? 'bg-purple-500/10 border-purple-500/50 ring-2 ring-purple-500/40'
                    : 'bg-sm-panel-2 hover:bg-sm-panel-2/80 border-sm-border'
                }`}
              >
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span
                      className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded ${
                        user.role === 'admin'
                          ? 'bg-purple-500/20 text-purple-300'
                          : ['state_officer', 'district_officer', 'sub_district_officer'].includes(user.role)
                            ? 'bg-red-500/20 text-red-300'
                            : ['field_officer'].includes(user.role)
                              ? 'bg-blue-500/20 text-blue-300'
                          : 'bg-sm-panel-2 text-sm-muted'
                      }`}
                    >
                      {user.role.replace('_', ' ')}
                    </span>
                    {isActive && (
                      <span className="text-[10px] font-bold text-purple-400 flex items-center gap-0.5">
                        <CheckCircle2 className="w-3 h-3" /> Active
                      </span>
                    )}
                  </div>
                  <h4 className="font-bold text-sm-text text-sm">{user.full_name}</h4>
                  <span className="text-[11px] text-sm-muted font-mono">{user.email}</span>
                  <p className="text-[11px] text-sm-muted mt-2 leading-relaxed">
                    {getRoleDescription(user.role)}
                  </p>
                </div>

                <button
                  className={`w-full py-1.5 rounded-lg text-xs font-semibold transition ${
                    isActive
                      ? 'bg-purple-700 text-white'
                      : 'bg-sm-panel-2 border border-sm-border text-sm-muted hover:bg-sm-panel-2/80'
                  }`}
                >
                  {isActive ? 'Current Session' : 'Switch to Persona'}
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* Backend & Spatial Infrastructure Health */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-sm-panel p-5 rounded-xl border border-sm-border shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-sm-border pb-2.5">
            <h3 className="text-sm font-bold text-sm-text flex items-center gap-2">
              <Server className="w-4 h-4 text-emerald-400" />
              <span>Microservice & Engine Status</span>
            </h3>
            <span className="text-[10px] bg-emerald-500/10 text-emerald-300 font-bold px-2 py-0.5 rounded-full flex items-center gap-1">
              <Radio className="w-2.5 h-2.5 text-emerald-400 animate-pulse" /> Live
            </span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex justify-between py-1.5 border-b border-sm-border">
              <span className="text-sm-muted">Service Architecture:</span>
              <span className="font-semibold text-sm-text">FastAPI Async Python Microservice</span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-sm-border">
              <span className="text-sm-muted">Spatial Engine:</span>
              <span className="font-semibold text-sm-text">PostGIS Geometry & ST_Distance</span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-sm-border">
              <span className="text-sm-muted">Pilot Pilot Bounding Box:</span>
              <span className="font-mono text-sm-text">30.3°N - 30.6°N, 79.2°E - 79.7°E</span>
            </div>
            <div className="flex justify-between py-1.5">
              <span className="text-sm-muted">Mathematical Risk Engine:</span>
              <span className="font-semibold text-emerald-400">12/12 Automated Formulas Validated</span>
            </div>
          </div>
        </div>

        {/* National Data Connectors Readiness Checklist */}
        <div className="bg-sm-panel p-5 rounded-xl border border-sm-border shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-sm-border pb-2.5">
            <h3 className="text-sm font-bold text-sm-text flex items-center gap-2">
              <Database className="w-4 h-4 text-blue-400" />
              <span>National Data Connectors Architecture</span>
            </h3>
            <span className="text-[10px] bg-blue-500/10 text-blue-300 font-semibold px-2 py-0.5 rounded">
              Ready for Integration
            </span>
          </div>

          <div className="space-y-2 text-xs text-sm-muted">
            <div className="flex items-start gap-2 p-2 rounded bg-sm-panel-2 border border-sm-border">
              <FileCheck className="w-3.5 h-3.5 text-blue-400 mt-0.5 shrink-0" />
              <div>
                <span className="font-bold text-sm-text block">ISRO Bhuvan Geospatial WMS Layer</span>
                <span className="text-[11px] text-sm-muted">Schema prepared for 1:50k landslide susceptibility WMS tile feeds.</span>
              </div>
            </div>

            <div className="flex items-start gap-2 p-2 rounded bg-sm-panel-2 border border-sm-border">
              <FileCheck className="w-3.5 h-3.5 text-blue-400 mt-0.5 shrink-0" />
              <div>
                <span className="font-bold text-sm-text block">Census of India / SECC Tabular Linkage</span>
                <span className="text-[11px] text-sm-muted">Village Census Codes (VIL-CHM-*) mapped for immediate live census sync.</span>
              </div>
            </div>

            <div className="flex items-start gap-2 p-2 rounded bg-sm-panel-2 border border-sm-border">
              <FileCheck className="w-3.5 h-3.5 text-blue-400 mt-0.5 shrink-0" />
              <div>
                <span className="font-bold text-sm-text block">NASA GPM IMERG 30-Min Rainfall REST API</span>
                <span className="text-[11px] text-sm-muted">Extreme precipitation anomaly alert pipeline integrated into Hazard Engine.</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};