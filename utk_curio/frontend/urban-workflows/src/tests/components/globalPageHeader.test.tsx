/**
 * The top bar every signed-in page wears: the section pages, the dataflow
 * canvas and its dashboard. Monitor sits left of API Settings; both go to their
 * pages from a section page and open drawers on the canvas and the dashboard.
 */
import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

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
// The canvas and the dashboard mount the two drawers' providers; a section
// page does not. Null stands for a section page.
let mockSettingsDrawer: { openApiSettings: jest.Mock } | null = null;
let mockMonitorDrawer: { openMonitor: jest.Mock } | null = null;
jest.mock('../../providers/ApiSettingsDrawerProvider', () => ({
  useApiSettingsDrawerOptional: () => mockSettingsDrawer,
}));
jest.mock('../../providers/MonitorDrawerProvider', () => ({
  useMonitorDrawerOptional: () => mockMonitorDrawer,
}));

import { GlobalPageHeader } from '../../components/layout/GlobalPageHeader';
import { requestAgentModel, requestSourceKey } from '../../components/apiSettings/apiSettingsRequest';

function Where() {
  const location = useLocation();
  return <div data-testid="settings-page">{location.pathname + location.search}</div>;
}

function renderAt(path: string, header: React.ReactElement = <GlobalPageHeader />) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/projects" element={<div data-testid="projects-page" />} />
        <Route path="/settings/:tab" element={<Where />} />
        <Route path="*" element={header} />
      </Routes>
    </MemoryRouter>
  );
}

const onTheCanvas = () => {
  mockSettingsDrawer = { openApiSettings: jest.fn() };
  mockMonitorDrawer = { openMonitor: jest.fn() };
};

beforeEach(() => {
  mockUser = { user: null, signout: jest.fn(), enableUserAuth: false };
  mockStandalone = false;
  mockSettingsDrawer = null;
  mockMonitorDrawer = null;
});

describe('GlobalPageHeader', () => {
  test('on a section page, links Monitor, unconditionally, just left of API Settings', () => {
    const { getByRole } = renderAt('/monitor');
    const monitor = getByRole('link', { name: 'Monitor' });
    const apiSettings = getByRole('link', { name: 'API Settings' });

    expect(monitor.getAttribute('href')).toBe('/monitor');
    expect(apiSettings.getAttribute('href')).toBe('/settings');
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

  test('on the settings page the API Settings link is current', () => {
    // The header renders on the page itself, so render it under /settings.
    render(
      <MemoryRouter initialEntries={['/settings/agents']}>
        <GlobalPageHeader />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'API Settings' }).getAttribute('aria-current')).toBe('page');
  });

  test('carries the attribute the canvas fit measures the bar by', () => {
    const { container } = renderAt('/monitor');
    expect(container.querySelector('header[data-curio-menu-bar="true"]')).not.toBeNull();
  });
});

describe('on the canvas and the dashboard', () => {
  test('Monitor and API Settings open their drawers and never leave the page', () => {
    onTheCanvas();
    renderAt('/dataflow/new');
    expect(screen.queryByRole('link', { name: 'Monitor' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'API Settings' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Monitor' }));
    expect(mockMonitorDrawer!.openMonitor).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'API Settings' }));
    expect(mockSettingsDrawer!.openApiSettings).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('settings-page')).toBeNull();
  });

  test("a card's request opens the drawer on the place it asked for", () => {
    onTheCanvas();
    renderAt('/dataflow/new');
    act(() => requestAgentModel('agent.dataflow-builder'));
    expect(mockSettingsDrawer!.openApiSettings).toHaveBeenCalledWith({
      section: 'agent-models',
      agentId: 'agent.dataflow-builder',
    });
    expect(screen.queryByTestId('settings-page')).toBeNull();
  });
});

describe("a card's request on a section page", () => {
  test('goes to the settings page on the place it asked for', () => {
    renderAt('/catalog/discovery');
    act(() => requestSourceKey('mapillary.token'));
    expect(screen.getByTestId('settings-page').textContent).toBe('/settings/keys?service=mapillary.token');
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
    const apiSettings = screen.getByRole('link', { name: 'API Settings' });

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
    onTheCanvas();
    renderAt('/dashboard/x');
    expect(screen.queryByRole('link', { name: 'Monitor' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Monitor' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'API Settings' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'API Settings' })).toBeNull();
    expect(screen.getByTestId('user-menu')).toBeTruthy();
  });
});
