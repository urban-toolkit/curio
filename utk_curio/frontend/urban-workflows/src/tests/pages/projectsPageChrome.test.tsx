/**
 * The /projects chrome after the navigation flatten.
 *
 * The page used to advertise the catalog through a small "Catalog" button in
 * the dark top bar and name itself with an <h1>Projects</h1>. Both are gone:
 * the top bar keeps only LLM Settings, and the section tab strip names the
 * page. Playwright tests wait on that tab now (wait_for_projects_page in
 * backend/tests/test_frontend/utils.py), so its accessible name matters.
 */
import React from 'react';
import { render, act, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

jest.mock('../../providers/UserProvider', () => ({
  useUserContext: () => ({ user: { name: 'Test User' }, signout: jest.fn(), enableUserAuth: true }),
}));
jest.mock('../../api/projectsApi', () => ({
  projectsApi: {
    list: jest.fn().mockResolvedValue([]),
    update: jest.fn(),
    duplicate: jest.fn(),
    delete: jest.fn(),
    create: jest.fn(),
  },
}));
jest.mock('../../NotebookConvertor', () => ({ notebookToTrill: jest.fn() }));
jest.mock('../../components/DataflowThumbnail', () => ({ __esModule: true, default: () => null }));
jest.mock('../../components/LlmSettingsModal', () => ({ __esModule: true, default: () => null }));
jest.mock('../../components/VersionBadge', () => ({ __esModule: true, default: () => null }));
// identity-obj-proxy hands back a symbol for Symbol.toPrimitive, which React
// cannot coerce into the <img src> attribute.
jest.mock('assets/curio-2.png', () => 'logo.png');

import ProjectsList from '../../pages/projects/ProjectsList';

async function renderPage() {
  let utils: ReturnType<typeof render>;
  await act(async () => {
    utils = render(
      <MemoryRouter initialEntries={['/projects']}>
        <ProjectsList />
      </MemoryRouter>
    );
  });
  return utils!;
}

describe('projects page chrome', () => {
  test('the top bar keeps only LLM Settings — no Catalog button', async () => {
    const { getByRole, queryByRole } = await renderPage();

    expect(getByRole('button', { name: 'LLM Settings' })).toBeTruthy();
    expect(queryByRole('button', { name: /catalog/i })).toBeNull();
  });

  test('the section tabs name the page instead of a heading', async () => {
    const { getByRole, queryByRole } = await renderPage();

    expect(queryByRole('heading')).toBeNull();
    const nav = getByRole('navigation', { name: 'Main sections' });
    expect(Array.from(nav.querySelectorAll('a')).map((a) => (a.textContent || '').trim())).toEqual([
      'Projects',
      'Node Catalog',
      'Data Catalog',
    ]);
  });

  test('the content spans the full width, like the catalog pages', async () => {
    const { getByPlaceholderText } = await renderPage();

    // The body used to sit in a centered 1200px column while the section tabs
    // above ran the full width — the two never shared a left edge.
    const inner = getByPlaceholderText('Search projects...').closest('main')
      ?.firstElementChild as HTMLElement;
    expect(inner.style.maxWidth).toBe('');
    expect(inner.style.margin).toBe('');
    expect(inner.style.padding).toBe('32px 20px');
  });

  test('exactly one link is named Projects, so the e2e locator is unambiguous', async () => {
    await renderPage();

    // wait_for_projects_page uses get_by_role("link", name="Projects",
    // exact=True); a second such link would be a strict-mode violation. The
    // logo link is safe — its accessible name comes from the img alt, "Curio".
    expect(screen.getAllByRole('link', { name: 'Projects' })).toHaveLength(1);
    expect(screen.getByRole('link', { name: 'Curio' })).toBeTruthy();
  });

  test('the projects actions and sign-out testid survive the header swap', async () => {
    const { getByRole, getByPlaceholderText, getByTestId } = await renderPage();

    expect(getByPlaceholderText('Search projects...')).toBeTruthy();
    expect(getByRole('button', { name: 'Import Jupyter notebook' })).toBeTruthy();
    expect(getByRole('button', { name: '+ New Dataflow' })).toBeTruthy();
    // backend/tests/test_frontend/test_auth_flow.py clicks this testid.
    expect(getByTestId('signout-button')).toBeTruthy();
  });
});
