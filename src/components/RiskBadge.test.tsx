import { describe, it, expect } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { RiskBadge } from './RiskBadge';

describe('RiskBadge UI Component', () => {
  it('renders Immediate Relocation with red styling and pulsate dot', () => {
    const html = renderToStaticMarkup(<RiskBadge level="Immediate Relocation" />);
    expect(html).toContain('Immediate Relocation');
    expect(html).toContain('bg-red-500/10');
    expect(html).toContain('bg-red-600');
  });

  it('renders Short-Term Relocation with amber styling', () => {
    const html = renderToStaticMarkup(<RiskBadge level="Short-Term Relocation" />);
    expect(html).toContain('Short-Term Relocation');
    expect(html).toContain('bg-amber-500/10');
  });

  it('renders Monitor Only with emerald styling', () => {
    const html = renderToStaticMarkup(<RiskBadge level="Monitor Only" />);
    expect(html).toContain('Monitor Only');
    expect(html).toContain('bg-emerald-500/10');
  });

  it('hides dot when showDot is false', () => {
    const html = renderToStaticMarkup(<RiskBadge level="Monitor Only" showDot={false} />);
    expect(html).toContain('Monitor Only');
    expect(html).not.toContain('animate-pulse');
  });
});
