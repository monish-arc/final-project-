import React, { useState, useEffect, useRef } from 'react';
import {
  UserCheck,
  ChevronDown,
  Activity,
  RotateCcw,
  Menu,
  LogOut,
  Bell,
} from 'lucide-react';
import { User, UserRole } from '../types';
import { DEMO_USERS } from '../data/mockData';
import { getAccessibleTabs, NavTab } from './Sidebar';
import { SafeMoveLogo } from './SafeMoveLogo';

interface NavbarProps {
  currentUser: User;
  onSwitchUser: (user: User) => void;
  onResetData: () => void;
  onSignOut?: () => void;
  activeTab?: NavTab;
  onSelectTab?: (tab: NavTab) => void;
  onOpenSidebar?: () => void;
  // The persona/role switcher is a development & testing aid only. It is
  // rendered for non-citizen portals in development builds; in a production
  // build the profile is static and a plain "Sign out" is shown instead.
  enableTestPersonaSwitcher?: boolean;
  regionLabel?: string;
}

export const Navbar: React.FC<NavbarProps> = ({
  currentUser,
  onSwitchUser,
  onResetData,
  onSignOut,
  activeTab,
  onSelectTab,
  onOpenSidebar,
  enableTestPersonaSwitcher = import.meta.env.DEV,
  regionLabel = 'India',
}) => {
  const currentTab: NavTab = activeTab ?? 'dashboard';
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!dropdownOpen) return undefined;
    const onPointerDown = (e: MouseEvent) => {
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDropdownOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [dropdownOpen]);

  const tabs = getAccessibleTabs(currentUser.role);
  const canAccess = (tab: NavTab) => tabs.includes(tab);
  const isCitizen = currentUser.role === 'normal_citizen';

  const getRoleBadge = (role: UserRole) => {
    switch (role) {
      case 'admin':
        return 'bg-purple-500/10 text-purple-300 border-purple-400/30';
      case 'state_officer':
      case 'district_officer':
      case 'sub_district_officer':
        return 'bg-blue-500/10 text-blue-300 border-blue-400/30';
      case 'field_officer':
        return 'bg-amber-500/10 text-amber-300 border-amber-400/30';
      case 'local_office':
        return 'bg-emerald-500/10 text-emerald-300 border-emerald-400/30';
      case 'gis_analysis_officer':
        return 'bg-cyan-500/10 text-cyan-300 border-cyan-400/30';
      case 'normal_citizen':
      default:
        return 'bg-slate-500/10 text-slate-300 border-slate-400/30';
    }
  };

  const quickLinks: { tab: NavTab; label: string; activeWhen?: NavTab[] }[] = [];
  if (canAccess('dashboard')) quickLinks.push({ tab: 'dashboard', label: 'Dashboard' });
  if (canAccess('map')) quickLinks.push({ tab: 'map', label: 'Interactive Map' });
  if (canAccess('alerts')) quickLinks.push({ tab: 'alerts', label: 'Risk Alerts' });
  if (canAccess('simulator') || canAccess('priority')) {
    quickLinks.push({ tab: 'simulator', label: 'Relocation Engine', activeWhen: ['simulator', 'priority'] });
  }
  if (canAccess('field_reports')) quickLinks.push({ tab: 'field_reports', label: 'Field Reports' });
  if (canAccess('evacuation')) quickLinks.push({ tab: 'evacuation', label: 'Evacuation Routes' });

  return (
    <header
      id="main-navigation-bar"
      className="bg-sm-panel text-sm-text border-b border-sm-border sticky top-0 z-40 shrink-0 shadow-sm"
    >
      {/* Top Advisory Ticker */}
      <div className="bg-sm-bg px-3 sm:px-6 py-1 border-b border-sm-border flex items-center justify-between text-xs text-sm-muted">
        <div className="flex items-center gap-2 overflow-hidden">
          <span className="flex items-center gap-1 text-sm-green font-semibold uppercase tracking-wider text-[10px] bg-sm-green/10 px-2 py-0.5 rounded border border-sm-green/30 shrink-0">
            <Activity className="w-3 h-3 animate-pulse" /> Live Monitoring
          </span>
          <span className="truncate text-[11px] text-sm-muted">
            Live hazard surveillance for {regionLabel}. Data streams from India-wide
            feeds: Open-Meteo weather, NASA GPM rainfall, GloFAS flood, OpenStreetMap
            villages and OSRM routing.
          </span>
        </div>
        <div className="hidden lg:flex items-center gap-4 shrink-0 text-sm-muted text-[11px]">
          <span>SafeMove AI &mdash; Government of India Disaster Management</span>
          <span className="font-mono text-sm-text">SAFEMOVE GIS v1.4</span>
        </div>
      </div>

      {/* Main Header Bar */}
      <div className="h-16 flex items-center justify-between px-3 sm:px-6 gap-2">
        {/* Hamburger (mobile only) */}
        <button
          id="mobile-sidenav-toggle-btn"
          onClick={onOpenSidebar}
          className="lg:hidden shrink-0 p-2 -ml-1 rounded-md hover:bg-white/5 text-sm-muted hover:text-sm-text transition cursor-pointer"
          aria-label="Open navigation"
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* Brand */}
        <div className="min-w-0 shrink">
          <SafeMoveLogo ariaLabel="SafeMove AI" />
          <p className="text-[10px] text-sm-muted uppercase tracking-widest leading-normal mt-1">
            Proactive Relocation &amp; Red-Zone Planning
          </p>
        </div>

        {/* Center Quick Navigation Links */}
        {quickLinks.length > 0 && (
          <div className="hidden md:flex items-center gap-6">
            <div className="flex gap-5 text-sm font-medium">
              {quickLinks.map(({ tab, label, activeWhen }) => {
                const isActive = activeWhen
                  ? activeWhen.includes(currentTab)
                  : currentTab === tab;
                return (
                  <button
                    key={tab}
                    onClick={() => onSelectTab?.(tab)}
                    className={`transition cursor-pointer ${
                      isActive
                        ? 'text-sm-green border-b-2 border-sm-green pb-1 font-semibold'
                        : 'text-sm-muted hover:text-sm-text pb-1'
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>

            <div className="h-8 w-[1px] bg-sm-border"></div>
          </div>
        )}

        {/* Right Side: Notifications, Reset Data & User Profile */}
        <div className="flex items-center gap-3 self-stretch">
          {canAccess('alerts') && (
            <button
              id="notifications-btn"
              onClick={() => onSelectTab?.('alerts')}
              title="Risk Alerts & notifications"
              aria-label="Risk Alerts & notifications"
              className="relative flex items-center justify-center w-9 h-9 rounded-md bg-sm-panel-2 hover:bg-white/5 border border-sm-border text-sm-muted hover:text-sm-text transition cursor-pointer"
            >
              <Bell className="w-4 h-4" />
              <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-sm-green" />
            </button>
          )}
          {!isCitizen && (
            <button
              id="reset-demo-data-btn"
              onClick={onResetData}
              title="Reset synthetic demo data to default"
              className="hidden sm:flex items-center gap-1.5 text-xs text-sm-muted hover:text-sm-text px-2.5 py-1.5 rounded-md bg-sm-panel-2 hover:bg-white/5 border border-sm-border transition"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Reset Data</span>
            </button>
          )}

          {isCitizen ? (
            <div className="flex items-center gap-3">
              <div className="leading-tight text-right hidden sm:block">
                <p className="text-xs font-bold text-sm-text truncate max-w-[130px]">
                  {currentUser.full_name}
                </p>
                <p className="text-[10px] text-sm-muted capitalize">
                  {currentUser.designation || `${currentUser.role.replace('_', ' ')}`}
                </p>
              </div>
              <div className="w-8 h-8 rounded-full bg-sm-panel-2 border border-sm-border flex items-center justify-center font-bold text-xs text-sm-text shadow-sm">
                {currentUser.full_name.charAt(0)}
              </div>
            </div>
          ) : enableTestPersonaSwitcher ? (
            <div ref={profileRef} className="relative flex items-center self-stretch">
              <button
                id="role-switcher-dropdown-btn"
                onClick={() => setDropdownOpen(!dropdownOpen)}
                aria-haspopup="menu"
                aria-expanded={dropdownOpen}
                className="flex items-center gap-3 text-right hover:opacity-90 transition focus:outline-none"
              >
                <div className="leading-tight text-right hidden sm:block">
                  <p className="text-xs font-bold text-sm-text truncate max-w-[130px]">
                    {currentUser.full_name}
                  </p>
                  <p className="text-[10px] text-sm-muted capitalize">
                    {currentUser.designation || currentUser.role.replace('_', ' ')}
                  </p>
                </div>
                <div className="w-8 h-8 rounded-full bg-sm-panel-2 border border-sm-border flex items-center justify-center font-bold text-xs text-sm-text shadow-sm">
                  {currentUser.full_name.charAt(0)}
                </div>
                <ChevronDown className="w-3.5 h-3.5 text-sm-muted" />
              </button>

              {dropdownOpen && (
                <div
                  id="role-switcher-menu"
                  role="menu"
                  className="absolute right-0 top-full mt-2 w-64 sm:w-72 max-w-[calc(100vw-1.5rem)] max-h-[65vh] overflow-y-auto bg-sm-panel border border-sm-border rounded-lg shadow-2xl py-2 z-50 animate-in fade-in slide-in-from-top-2"
                >
                  <div className="px-3 py-2 border-b border-sm-border">
                    <p className="text-xs font-semibold text-sm-text uppercase tracking-wider">
                      Switch Test Persona / Role
                    </p>
                    <p className="text-[11px] text-sm-muted">
                      Test different RBAC permission sets
                    </p>
                  </div>
                  <div className="p-1 space-y-1">
                    {DEMO_USERS.map((user) => (
                      <button
                        key={user.id}
                        id={`switch-user-${user.username}`}
                        onClick={() => {
                          onSwitchUser(user);
                          setDropdownOpen(false);
                        }}
                        className={`w-full text-left px-3 py-2 rounded text-xs flex items-start gap-2 transition ${
                          currentUser.id === user.id
                            ? 'bg-sm-green/15 text-sm-text'
                            : 'text-sm-muted hover:bg-white/5'
                        }`}
                      >
                        <UserCheck
                          className={`w-4 h-4 mt-0.5 ${
                            currentUser.id === user.id ? 'text-sm-green' : 'text-slate-500'
                          }`}
                        />
                        <div className="overflow-hidden">
                          <div className="flex items-center gap-1.5">
                            <span className="font-semibold text-sm-text">{user.full_name}</span>
                            <span
                              className={`text-[10px] px-1.5 py-0.2 rounded border font-medium ${getRoleBadge(
                                user.role
                              )}`}
                            >
                              {user.role.replace('_', ' ')}
                            </span>
                          </div>
                          <p className="text-[10px] text-sm-muted truncate mt-0.5">
                            {user.designation}
                          </p>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <div className="leading-tight text-right hidden sm:block">
                <p className="text-xs font-bold text-sm-text truncate max-w-[130px]">
                  {currentUser.full_name}
                </p>
                <p className="text-[10px] text-sm-muted capitalize">
                  {currentUser.designation || currentUser.role.replace('_', ' ')}
                </p>
              </div>
              <div className="w-8 h-8 rounded-full bg-sm-panel-2 border border-sm-border flex items-center justify-center font-bold text-xs text-sm-text shadow-sm">
                {currentUser.full_name.charAt(0)}
              </div>
              <button
                id="sign-out-btn"
                onClick={onSignOut}
                title="Sign out"
                aria-label="Sign out"
                className="flex items-center justify-center w-8 h-8 rounded-md bg-sm-panel-2 hover:bg-white/5 border border-sm-border text-sm-muted hover:text-sm-text transition cursor-pointer"
              >
                <LogOut className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};