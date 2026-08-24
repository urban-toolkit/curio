/**
 * The /projects chrome, now built in the shape of the catalog browse pages:
 * a category rail for filtering, a card area, and a detail drawer.
 *
 * The old dark-bar "Catalog" button is gone (the section tabs replaced it),
 * and Playwright waits on the Projects tab link rather than a heading
 * (wait_for_projects_page in backend/tests/test_frontend/utils.py), so that
 * link's accessible name matters.
 */
import React from 'react';
import { render, act, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const PROJECTS = [
  {
    id: 'p1',
    name: 'Air quality',
    slug: 'air-quality',
    description: 'Sensor readings',
    thumbnail_accent: 'sky',
    spec_revision: 4,
    last_opened_at: '2026-02-01T10:00:00Z',
    created_at: '2026-01-01T10:00:00Z',
    updated_at: '2026-02-02T10:00:00Z',
    archived_at: null,
    graph_preview: { nodes: [{ id: 'a', type: 't', x: 0, y: 0 }], edges: [] },
  },
  {
    id: 'p2',
    name: 'Bike lanes',
    slug: 'bike-lanes',
    description: null,
    thumbnail_accent: 'mint',
    spec_revision: 1,
    last_opened_at: null,
    created_at: '2026-01-05T10:00:00Z',
    updated_at: '2026-01-06T10:00:00Z',
    archived_at: null,
    graph_preview: null,
  },
];

const mockList = jest.fn();

jest.mock('../../providers/UserProvider', () => ({
  useUserContext: () => ({ user: { name: 'Test User' }, signout: jest.fn(), enableUserAuth: true }),
}));
jest.mock('../../api/projectsApi', () => ({
  projectsApi: {
    list: (...args: unknown[]) => mockList(...args),
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

import ProjectsList from '../../pages/projects/ProjectsList';

/** The page fetches every scope at once so the rail can show counts. */
function stubScopes(byScope: Record<string, unknown[]>) {
  mockList.mockImplementation((params: { scope?: string }) =>
    Promise.resolve(byScope[params?.scope ?? 'mine'] ?? [])
  );
}

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

beforeEach(() => {
  mockList.mockReset();
  stubScopes({ mine: PROJECTS, recent: [PROJECTS[0]], archived: [] });
});

describe('projects page chrome', () => {
  test('the top bar keeps only LLM Settings — no Catalog button', async () => {
    const { getByRole, queryByRole } = await renderPage();

    expect(getByRole('button', { name: 'LLM Settings' })).toBeTruthy();
    expect(queryByRole('button', { name: /catalog/i })).toBeNull();
  });

  test('the section tabs sit above the page', async () => {
    const { getByRole } = await renderPage();

    const nav = getByRole('navigation', { name: 'Main sections' });
    expect(Array.from(nav.querySelectorAll('a')).map((a) => (a.textContent || '').trim())).toEqual([
      'Projects',
      'Node Catalog',
      'Data Catalog',
    ]);
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

describe('projects filter rail', () => {
  test('the rail lists each scope with its count', async () => {
    const { getByRole } = await renderPage();

    const rail = getByRole('complementary', { name: 'Project filters' });
    expect(
      Array.from(rail.querySelectorAll('button')).map((b) => (b.textContent || '').trim())
    ).toEqual(['All projects2', 'Recent1', 'Archived0']);
  });

  test('the active scope is the pressed rail button, and picking one refilters', async () => {
    const { getByRole } = await renderPage();

    const rail = getByRole('complementary', { name: 'Project filters' });
    const railButton = (label: string) =>
      Array.from(rail.querySelectorAll('button')).find((b) =>
        (b.textContent || '').startsWith(label)
      ) as HTMLButtonElement;

    expect(railButton('All projects').getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText('Bike lanes')).toBeTruthy();

    await act(async () => {
      fireEvent.click(railButton('Recent'));
    });

    expect(railButton('Recent').getAttribute('aria-pressed')).toBe('true');
    expect(railButton('All projects').getAttribute('aria-pressed')).toBe('false');
    // "recent" holds only the first project.
    expect(screen.queryByText('Bike lanes')).toBeNull();
  });

  test('an empty scope shows the empty state and no card area', async () => {
    const { getByRole, container } = await renderPage();

    const rail = getByRole('complementary', { name: 'Project filters' });
    const archived = Array.from(rail.querySelectorAll('button')).find((b) =>
      (b.textContent || '').startsWith('Archived')
    ) as HTMLButtonElement;

    await act(async () => {
      fireEvent.click(archived);
    });

    expect(screen.getByText('No projects yet. Create a new dataflow!')).toBeTruthy();
    expect(container.querySelector('[data-curio-projects-scroll="true"]')).toBeNull();
  });
});

describe('projects detail drawer', () => {
  test('the first project is selected so the drawer arrives populated', async () => {
    const { getByRole } = await renderPage();

    expect(getByRole('heading', { name: 'Air quality' })).toBeTruthy();
    expect(getByRole('button', { name: 'Open dataflow' })).toBeTruthy();
    // graph_preview carries one node and no edges.
    expect(screen.getByText('Nodes').nextElementSibling?.textContent).toBe('1');
    expect(screen.getByText('Connections').nextElementSibling?.textContent).toBe('0');
  });

  test('clicking a card moves the selection', async () => {
    const { container, getByRole } = await renderPage();

    const second = container.querySelector('[data-project-id="p2"]') as HTMLElement;
    await act(async () => {
      fireEvent.click(second);
    });

    expect(getByRole('heading', { name: 'Bike lanes' })).toBeTruthy();
  });

  test('an unarchived project offers Archive, not Delete forever', async () => {
    const { getByRole, queryByRole } = await renderPage();

    expect(getByRole('button', { name: 'Archive' })).toBeTruthy();
    expect(queryByRole('button', { name: 'Delete forever' })).toBeNull();
  });

  test('closing the drawer collapses it', async () => {
    const { getByRole, queryByRole } = await renderPage();

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'Close details' }));
    });

    expect(queryByRole('button', { name: 'Open dataflow' })).toBeNull();
  });
});
