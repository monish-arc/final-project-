import { describe, it, expect } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Navbar } from './Navbar';
import { DEMO_USERS } from '../data/mockData';

const admin = DEMO_USERS.find((u) => u.username === 'admin');
const citizen = DEMO_USERS.find((u) => u.username === 'citizen');

const baseProps = {
  onSwitchUser: () => {},
  onResetData: () => {},
  onSelectTab: () => {},
  activeTab: 'dashboard' as const,
};

describe('Navbar persona switcher gating', () => {
  it('hides the test persona dropdown in production (non-citizen profile is static, with sign-out)', () => {
    const html = renderToStaticMarkup(
      <Navbar
        {...baseProps}
        currentUser={admin!}
        enableTestPersonaSwitcher={false}
        onSignOut={() => {}}
      />
    );
    expect(html).not.toContain('role-switcher-dropdown-btn');
    expect(html).toContain(admin!.full_name);
    expect(html).toContain('sign-out-btn');
  });

  it('shows the test persona dropdown only in development (non-citizen)', () => {
    const html = renderToStaticMarkup(
      <Navbar {...baseProps} currentUser={admin!} enableTestPersonaSwitcher onSignOut={() => {}} />
    );
    expect(html).toContain('role-switcher-dropdown-btn');
  });

  it('keeps the citizen profile static — dev persona UI never applies to the reference portal', () => {
    const html = renderToStaticMarkup(
      <Navbar {...baseProps} currentUser={citizen!} enableTestPersonaSwitcher onSignOut={() => {}} />
    );
    expect(html).not.toContain('role-switcher-dropdown-btn');
    expect(html).toContain('sign-out-btn');
    expect(html).toContain(citizen!.full_name);
  });
});