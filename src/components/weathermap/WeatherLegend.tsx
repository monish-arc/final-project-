import React from 'react';
import { VariableMeta, FLOOD_RISK_COLORS, legendTickLabels } from '../../lib/weatherLayers';

interface WeatherLegendProps {
  meta?: VariableMeta;
  flood?: boolean;
  isHistorical: boolean;
  historicalLabel: string;
}

/** Bottom-right legend for the weather/food layer. Rainfall (and any layer
 *  with discrete `stops`) renders a Windy-style stepped scale; continuous
 *  layers render a gradient with the two domain endpoints; flood layers
 *  render the LOW→EXTREME risk scale. */
export const WeatherLegend: React.FC<WeatherLegendProps> = ({
  meta,
  flood = false,
  isHistorical,
  historicalLabel,
}) => {
  if (!meta && !flood) return null;

  const gradient = flood
    ? 'linear-gradient(90deg,' + Object.values(FLOOD_RISK_COLORS).join(',') + ')'
    : `linear-gradient(90deg, ${meta!.colors[0]}, ${meta!.colors[meta!.colors.length - 1]})`;

  const ticks = meta ? legendTickLabels(meta) : ['LOW', 'EXTREME'];

  return (
    <div className="absolute bottom-24 right-3 z-20 pointer-events-none bg-slate-950/75 backdrop-blur-md border border-slate-700/80 rounded-xl px-3 py-2 max-w-56">
      <div className="w-48 h-2 rounded-full" style={{ background: gradient }} />
      <div className="flex justify-between text-[8px] text-slate-400 mt-0.5 w-48 leading-tight">
        {ticks.map((t, i) => (
          <span key={i} className="whitespace-nowrap">{t}</span>
        ))}
      </div>
      <p className="text-[9px] text-slate-500 mt-1 truncate max-w-48">
        {flood
          ? isHistorical
            ? `Flood risk · ERA5 ${historicalLabel}`
            : 'Rule-based flood risk'
          : `${meta!.label} (${meta!.unit})`}
      </p>
    </div>
  );
};