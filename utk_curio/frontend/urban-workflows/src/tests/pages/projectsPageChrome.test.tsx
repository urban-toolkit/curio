/**
 * The /projects chrome, now built in the shape of the catalog browse pages:
 * a category rail for filtering, a card area, and a detail drawer.
 *
 * The old dark-bar "Catalog" button is gone (the section tabs replaced it),
 * and Playwright waits on the Projects tab link rather than a heading
 * (wait_for_projects_page in backend/tests/test_frontend/utils.py), so that
 * link's accessible name matters.
 */
import fs from 'fs';
import path from 'path';
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
jest.mock('../../components/AiSettingsModal', () => ({ __esModule: true, default: () => null }));
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
  test('the top bar keeps only AI Settings — no Catalog button', async () => {
    const { getByRole, queryByRole } = await renderPage();

    expect(getByRole('button', { name: 'AI Settings' })).toBeTruthy();
    expect(queryByRole('button', { name: /catalog/i })).toBeNull();
  });

  test('the section tabs sit above the page', async () => {
    const { getByRole } = await renderPage();

    const nav = getByRole('navigation', { name: 'Main sections' });
    expect(Array.from(nav.querySelectorAll('a')).map((a) => (a.textContent || '').trim())).toEqual([
      'Projects',
      'Node Catalog',
      'Data Catalog',
      'Agent Catalog',
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

    expect(getByPlaceholderText('Search projects…')).toBeTruthy();
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

describe('project card selection', () => {
  const read = (rel: string) =>
    fs.readFileSync(path.resolve(__dirname, '../../pages', rel), 'utf8');
  /** The declarations of one rule, found textually — no escaping to get wrong. */
  const ruleBody = (css: string, selector: string) => {
    const start = css.indexOf('.' + selector + ' {');
    expect(start).toBeGreaterThan(-1);
    return css.slice(start, css.indexOf('}', start));
  };
  const boxShadow = (css: string, selector: string) => {
    const declaration = ruleBody(css, selector)
      .split(';')
      .find((d) => d.includes('box-shadow'));
    expect(declaration).toBeDefined();
    // The two stylesheets space rgba() differently; only the values matter.
    return (declaration as string).split('box-shadow:')[1].split(' ').join('');
  };

  test('only the selected card is marked, by the card itself', async () => {
    const { container } = await renderPage();

    const card = (id: string) =>
      container.querySelector('[data-project-id="' + id + '"]') as HTMLElement;

    expect(card('p1')).toHaveClass('cardActive');
    expect(card('p2')).not.toHaveClass('cardActive');
    // The corner dot was a second, redundant selection marker; the accented
    // border and lift are the only indicator now, on all three browse tabs.
    expect(container.querySelector('.selectedDot')).toBeNull();
  });

  test('the selected card lifts by the same shadow as a selected catalog card', () => {
    // The reported mismatch: projects used a flat dark ring while the catalog
    // raises the card and tints its border with the item's own accent.
    expect(boxShadow(read('projects/ProjectsBrowseLayout.module.css'), 'cardActive')).toBe(
      boxShadow(read('catalog/CatalogBrowseLayout.module.css'), 'cardActive')
    );
  });

  test('every dataflow card carries the same colour, whatever its accent', async () => {
    // Dataflows have no categorization, so colour here cannot mean anything.
    // The catalog pages key a card's colour to something real (a dataset's
    // format, a package's node category); this page used to key it to
    // `thumbnail_accent`, which is set by nothing and read as noise beside
    // them. p1 is "sky" and p2 is "peach" in the fixture; neither reaches the
    // DOM.
    const { container } = await renderPage();

    for (const id of ['p1', 'p2']) {
      const card = container.querySelector('[data-project-id="' + id + '"]') as HTMLElement;
      expect(card.style.getPropertyValue('--projectAccent')).toBe('');
      expect(card.getAttribute('style')).toBeNull();
    }

    const layout = read('projects/ProjectsBrowseLayout.module.css');
    expect(ruleBody(layout, 'cardActive')).toContain(
      'border-color: var(--curio-kind-dataflow-fg)'
    );
    expect(ruleBody(layout, 'cardStrip')).toContain('background: var(--curio-kind-dataflow-fg)');
  });

  test('the header carries the same chrome as the catalog browse pages', async () => {
    // The three browse pages are peers, so /projects grows the kind icon and
    // the sort select that both catalogs already had.
    const { container, getByRole } = await renderPage();

    expect(container.querySelector('.titleRow .kindIcon')).not.toBeNull();
    expect(getByRole('combobox', { name: 'Sort projects' })).toBeTruthy();
  });

  test('no browse page carries a scope chip beside its search box', () => {
    // Removed on all three at once: the chip restated the page you were
    // already on, and the class is gone so it cannot come back on one page
    // only.
    expect(read('catalog/CatalogBrowseLayout.module.css')).not.toContain('.hubStatusChip');
    for (const page of [
      'projects/ProjectsList.tsx',
      'catalog/NodeCatalogBrowse.tsx',
      'dataHub/DataCatalogBrowse.tsx',
    ]) {
      expect(read(page)).not.toContain('hubStatusChip');
    }
  });
});

describe('projects detail drawer', () => {
  test('the first project is selected so the drawer arrives populated', async () => {
    const { getByRole } = await renderPage();

    expect(getByRole('heading', { name: 'Air quality' })).toBeTruthy();
    expect(getByRole('button', { name: 'Open dataflow' })).toBeTruthy();
    // graph_preview carries one node and no edges; the meta row states both,
    // in the slot where the catalogs put "N nodes · packageId".
    expect(screen.getByText('1 nodes · 0 connections')).toBeTruthy();
    expect(screen.getByText('Sensor readings')).toBeTruthy();
  });

  test('the selected name renders twice: on the card and in the drawer heading', async () => {
    const { container, getByRole } = await renderPage();

    // This duplication is deliberate, and it is why the e2e suite cannot look a
    // project up by bare text: with one project on the page, get_by_text(name)
    // matches both nodes and Playwright fails it as a strict mode violation.
    // project_card() in backend/tests/test_frontend/utils.py scopes to the card
    // via the two selectors asserted here, so this test guards that contract.
    const card = container.querySelector(
      '[data-curio-projects-scroll="true"] [data-project-id="p1"]'
    ) as HTMLElement;
    expect(card).not.toBeNull();
    expect(card.textContent).toContain('Air quality');
    expect(getByRole('heading', { name: 'Air quality' })).toBeTruthy();
    expect(screen.getAllByText('Air quality').length).toBe(2);
  });

  test('the drawer is the shared catalog body, not a projects-only one', async () => {
    const { container, getByRole } = await renderPage();

    // Both catalogs render through CatalogBrowseDrawerBody; this page used to
    // hand-assemble its own markup, which is how the drawers drifted apart.
    expect(container.querySelector('.drawerKindHero')).not.toBeNull();
    expect(container.querySelector('.drawerDatasetName')).not.toBeNull();
    expect(container.querySelector('.drawerMeta')).not.toBeNull();
    expect(container.querySelector('.drawerCtas')).not.toBeNull();
    // Standard uppercase section label plus infoRow pairs, not bespoke rows.
    expect(screen.getByText('Dataflow info')).toBeTruthy();
    expect(container.querySelectorAll('.infoRow').length).toBeGreaterThan(0);
    // The primary action uses the catalog's own primary-button class.
    expect(getByRole('button', { name: 'Open dataflow' })).toHaveClass('addToPaletteBtn');
  });

  test('the header names the kind and the badges carry the revision', async () => {
    const { container } = await renderPage();

    expect(screen.getByText('Dataflow details')).toBeTruthy();
    expect(container.querySelector('.drawerCategoryBadge')?.textContent).toBe('Rev 4');
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
      // CatalogBrowseDrawerBody labels its close button "Close", as on both catalogs.
      fireEvent.click(getByRole('button', { name: 'Close' }));
    });

    expect(queryByRole('button', { name: 'Open dataflow' })).toBeNull();
  });
});
