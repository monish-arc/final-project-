import React from 'react';
import { WeatherMap } from '../components/weathermap/WeatherMap';
import type { RegionViewportFocus } from '../lib/regionViewport';
import type { DataStatusEntry, UserRole } from '../types';

interface WeatherForecastMapPageProps {
  focus?: RegionViewportFocus | null;
  regionLabel?: string;
  dataStatus?: DataStatusEntry[] | null;
  userRole?: UserRole;
}

/**
 * Weather & Hazard Map — replaces the old forecast map on the weather tab.
 * The legacy `WeatherForecastMap` component remains in the codebase (unused);
 * this page hosts the new full-screen Windy-style map: dark basemap, layer
 * panel (Weather / Hazards / Terrain), hourly NOW+48h timeline, animated wind
 * particles from real u/v, point picker and honest source/provenance chips.
 * `dataStatus` is accepted for back-compat with the App wrapper but the map
 * surfaces per-layer live status itself. Live-provider configuration stays
 * administrative-only (any userRole other than admin sees a read-only panel).
 */
export const WeatherForecastMapPage: React.FC<WeatherForecastMapPageProps> = ({
  focus = null,
  regionLabel = 'India',
  dataStatus = null,
  userRole = 'admin',
}) => {
  void dataStatus;
  return (
    // `flex-none` (`flex: 0 0 auto`) is the critical part: `<main>` is a column
    // flexbox, so a `flex-1` child would be sized by flex distribution
    // (`flex-basis: 0` applies to HEIGHT here) instead of by its content. That
    // kept the page exactly as tall as the viewport, so `<main>`'s
    // `overflow-y-auto` had no overflow to scroll to and the map below the
    // Layers panel was unreachable. With `flex-none` the page keeps its natural
    // content height, which overflows `<main>` and makes it scrollable.
    <div id="weather-hazard-map-view" className="flex flex-col flex-none">
      <WeatherMap
        focus={focus}
        regionLabel={regionLabel}
        canManageLiveProviders={userRole === 'admin'}
      />
    </div>
  );
};

export default WeatherForecastMapPage;