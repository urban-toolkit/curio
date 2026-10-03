/**
 * The top bar's Monitor link, which sits left of API Settings.
 */
import React from 'react';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// No user and no auth, the state a laptop instance starts in. The monitor
// exists on every instance, not only a --deploy one, so if someone later gates
// the link on context state, this fails rather than silently hiding the page.
jest.mock('../../providers/UserProvider', () => ({
  useUserContext: () => ({ user: null, signout: jest.fn(), enableUserAuth: false }),
}));
jest.mock('../../components/ApiSettingsModal', () => ({ __esModule: true, default: () => null }));

import { GlobalPageHeader } from '../../components/layout/GlobalPageHeader';

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <GlobalPageHeader />
    </MemoryRouter>
  );
}

describe('GlobalPageHeader', () => {
  test('links Monitor, unconditionally, just left of API Settings', () => {
    const { getByRole } = renderAt('/projects');
    const monitor = getByRole('link', { name: 'Monitor' });
    const apiSettings = getByRole('button', { name: 'API Settings' });

    expect(monitor.getAttribute('href')).toBe('/monitor');
    expect(monitor.parentElement).toBe(apiSettings.parentElement);
    expect(monitor.nextElementSibling).toBe(apiSettings);
  });

  test.each([
    ['/monitor', 'page'],
    ['/projects', null],
  ])('on %s the Monitor link has aria-current=%s', (path, current) => {
    const { getByRole } = renderAt(path);
    expect(getByRole('link', { name: 'Monitor' }).getAttribute('aria-current')).toBe(current);
  });
});
