/**
 * The top bar every signed-in page wears: the section pages, the dataflow
 * canvas and its dashboard. Its Monitor link sits left of API Settings.
 */
import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

// No user and no auth by default, the state a laptop instance starts in. The
// monitor exists on every instance, not only a --deploy one, so if someone
// later gates the link on context state, this fails rather than silently
// hiding the page.
let mockUser: any = { user: null, signout: jest.fn(), enableUserAuth: false };
let mockStandalone = false;
jest.mock('../../providers/UserProvider', () => ({
  useUserContext: () => mockUser,
}));
jest.mock('../../standalone/dashboardPayload', () => ({
  isStandaloneDashboard: () => mockStandalone,
}));
jest.mock('../../components/ApiSettingsModal', () => ({ __esModule: true, default: () => null }));

import { GlobalPageHeader } from '../../components/layout/GlobalPageHeader';

function renderAt(path: string, header: React.ReactElement = <GlobalPageHeader />) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/projects" element={<div data-testid="projects-page" />} />
        <Route path="*" element={header} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  mockUser = { user: null, signout: jest.fn(), enableUserAuth: false };
  mockStandalone = false;
});

describe('GlobalPageHeader', () => {
  test('links Monitor, unconditionally, just left of API Settings', () => {
    const { getByRole } = renderAt('/monitor');
    const monitor = getByRole('link', { name: 'Monitor' });
    const apiSettings = getByRole('button', { name: 'API Settings' });

    expect(monitor.getAttribute('href')).toBe('/monitor');
    expect(monitor.parentElement).toBe(apiSettings.parentElement);
    expect(monitor.nextElementSibling).toBe(apiSettings);
  });

  test.each([
    ['/monitor', 'page'],
    ['/catalog/nodes', null],
  ])('on %s the Monitor link has aria-current=%s', (path, current) => {
    const { getByRole } = renderAt(path);
    expect(getByRole('link', { name: 'Monitor' }).getAttribute('aria-current')).toBe(current);
  });

  test('carries the attribute the canvas fit measures the bar by', () => {
    const { container } = renderAt('/monitor');
    expect(container.querySelector('header[data-curio-menu-bar="true"]')).not.toBeNull();
  });
});

describe('the page slot', () => {
  test("puts a page's own controls between the logo and the account", () => {
    renderAt(
      '/dataflow/new',
      <GlobalPageHeader>
        <button type="button">File menu</button>
      </GlobalPageHeader>,
    );
    const logo = screen.getByRole('link', { name: 'Curio' });
    const control = screen.getByRole('button', { name: 'File menu' });
    const apiSettings = screen.getByRole('button', { name: 'API Settings' });

    const follows = (a: Node, b: Node) =>
      Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(follows(logo, control)).toBe(true);
    expect(follows(control, apiSettings)).toBe(true);
  });

  test('a section page passes nothing and gets no empty slot', () => {
    const { container } = renderAt('/catalog/nodes');
    expect(container.querySelector('.slot')).toBeNull();
  });
});

describe('the logo', () => {
  test('goes to Projects', () => {
    renderAt('/catalog/nodes');
    fireEvent.click(screen.getByRole('link', { name: 'Curio' }));
    expect(screen.getByTestId('projects-page')).toBeTruthy();
  });

  test('asks first on a page with unsaved work, and goes only when told to', () => {
    let go: (() => void) | null = null;
    const onLeave = jest.fn((next: () => void) => { go = next; });
    renderAt('/dataflow/new', <GlobalPageHeader onLeave={onLeave} />);

    fireEvent.click(screen.getByRole('link', { name: 'Curio' }));
    expect(onLeave).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('projects-page')).toBeNull();

    act(() => go!());
    expect(screen.getByTestId('projects-page')).toBeTruthy();
  });
});

describe('the account', () => {
  test('offers to sign in when nobody is', () => {
    renderAt('/monitor');
    expect(screen.getByTestId('login-link').getAttribute('href')).toBe('/auth/signin');
  });

  test("shows the user's picture when they have one, and Sign out under auth", () => {
    mockUser = {
      user: { name: 'Ada Lovelace', username: 'ada', profile_image: '/ada.png' },
      signout: jest.fn(),
      enableUserAuth: true,
    };
    renderAt('/projects/x');
    expect(screen.getByRole('img', { name: 'Ada Lovelace' }).getAttribute('src')).toBe('/ada.png');
    expect(screen.getByTestId('signout-button')).toBeTruthy();
  });

  test('falls back to initials from the username', () => {
    mockUser = { user: { name: '', username: 'grace hopper' }, signout: jest.fn(), enableUserAuth: false };
    renderAt('/projects/x');
    expect(screen.getByLabelText('user avatar').textContent).toBe('GH');
    expect(screen.queryByTestId('signout-button')).toBeNull();
  });
});

describe('a standalone dashboard', () => {
  test('has no server to monitor and no keys to set', () => {
    mockStandalone = true;
    mockUser = { user: { name: 'Viewer', username: 'guest_shared' }, signout: jest.fn(), enableUserAuth: false };
    renderAt('/dashboard/x');
    expect(screen.queryByRole('link', { name: 'Monitor' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'API Settings' })).toBeNull();
    expect(screen.getByTestId('user-menu')).toBeTruthy();
  });
});
