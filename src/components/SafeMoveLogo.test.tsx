import { describe, it, expect } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { SafeMoveLogo } from './SafeMoveLogo';

describe('SafeMoveLogo', () => {
  it('renders the SafeMove AI wordmark in the full variant', () => {
    const html = renderToStaticMarkup(<SafeMoveLogo />);
    expect(html).toContain('SafeMove AI');
    expect(html).toContain('<svg');
  });

  it('renders an icon-only mark when variant=icon (no wordmark, still accessible)', () => {
    const html = renderToStaticMarkup(<SafeMoveLogo variant="icon" />);
    expect(html).not.toContain('SafeMove AI');
    expect(html).toContain('<svg');
    expect(html).toContain('aria-hidden');
  });

  it('honours a custom aria-label and className', () => {
    const html = renderToStaticMarkup(
      <SafeMoveLogo ariaLabel="SafeMove AI home" className="h-9 w-9" />
    );
    expect(html).toContain('aria-label="SafeMove AI home"');
    expect(html).toContain('h-9');
  });

  it('uses the green brand colour inside the mark', () => {
    const html = renderToStaticMarkup(<SafeMoveLogo variant="icon" />);
    expect(html.toLowerCase()).toContain('22c55e');
  });
});