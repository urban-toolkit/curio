/**
 * Regression test for #161 — the projects page had no scrollbar.
 *
 * MainCanvas.css sets `html, body { overflow: hidden }` and, being a plain
 * (non-module) import in a statically-imported component, style-loader injects
 * it for every route. ProjectsList used `minHeight: 100vh` and relied on
 * document scroll, so once the grid passed the viewport the rest was
 * unreachable. The catalog pages already solve this by owning their scroll
 * within the viewport; this pins ProjectsList to the same shape.
 *
 * The page is now laid out like the catalog browse pages (rail | cards |
 * drawer), so the scrolling region is the card area rather than the whole main
 * column, and its overflow lives in a CSS module. jsdom applies no CSS, so the
 * geometry half is asserted against the stylesheet on disk — the same approach
 * as tests/catalog/removedCatalogChrome.test.ts.
 */
// ProjectsList toasts the outcome of a delete (#221), and the real
// provider is not mounted in these tests. Same stub the other page and drawer
// suites use.
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

import fs from 'fs';
import path from 'path';
import React from 'react';
import { render, act } from '@testing-library/react';

jest.mock('../../providers/UserProvider', () => ({
  useUserContext: () => ({ user: { name: 'Test User' }, signout: jest.fn(), enableUserAuth: false }),
}));
jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock('../../api/projectsApi', () => ({
  projectsApi: {
    list: jest.fn().mockResolvedValue([
      {
        id: 'p1',
        name: 'Only project',
        slug: 'only-project',
        description: null,
        thumbnail_accent: 'peach',
        spec_revision: 1,
        last_opened_at: null,
        created_at: '2026-01-01T10:00:00Z',
        updated_at: '2026-01-01T10:00:00Z',
        graph_preview: null,
      },
    ]),
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
jest.mock('react-router-dom', () => ({
  useNavigate: () => jest.fn(),
  Link: ({ children }: any) => <a>{children}</a>,
  // GlobalPageHeader / AppSectionTabs render outside a Router here.
  NavLink: ({ children }: any) => <a>{children}</a>,
}));

import ProjectsList from '../../pages/projects/ProjectsList';

const LAYOUT_CSS = fs.readFileSync(
  path.resolve(__dirname, '../../pages/projects/ProjectsBrowseLayout.module.css'),
  'utf8'
);

// The page shell is the catalog's, shared rather than restated: ProjectsList
// used to carry an inline style object whose own comment said it was the same
// shape as `.pageShell`.
const SHELL_CSS = fs.readFileSync(
  path.resolve(__dirname, '../../pages/catalog/CatalogMasterPage.module.css'),
  'utf8'
);

/** The declarations inside one rule of a stylesheet (the layout by default). */
function rule(selector: string, css: string = LAYOUT_CSS): string {
  const match = css.match(new RegExp('\\.' + selector + '\\s*\\{([^}]*)\\}'));
  expect(match).not.toBeNull();
  return (match as RegExpMatchArray)[1];
}

/** Render and let the initial projectsApi.list() promises settle. */
async function renderSettled() {
  let utils: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<ProjectsList />);
  });
  return utils!;
}

describe('ProjectsList scroll ownership', () => {
  test('the shell is bounded to the viewport', async () => {
    const { container } = await renderSettled();

    // The shape moved from an inline style object to the shared `.pageShell`,
    // so the guarantee is asserted against the stylesheet — the same approach
    // the sibling tests below already use for `.cardScroll`.
    const page = container.firstElementChild as HTMLElement;
    expect(page).toHaveClass('pageShell');

    const shell = rule('pageShell', SHELL_CSS);
    // Bounded height, not min-height: with html/body overflow hidden, a page
    // that merely grows past the viewport just gets clipped.
    expect(shell).toMatch(/height:\s*100vh/);
    expect(shell).toMatch(/overflow:\s*hidden/);
    expect(shell).toMatch(/display:\s*flex/);
    expect(shell).toMatch(/flex-direction:\s*column/);
  });

  test('the card area is the scrolling region', async () => {
    const { container } = await renderSettled();

    const scroller = container.querySelector('[data-curio-projects-scroll="true"]');
    expect(scroller).not.toBeNull();
    // identity-obj-proxy maps CSS modules to their own key names.
    expect(scroller).toHaveClass('cardScroll');

    const cardScroll = rule('cardScroll');
    expect(cardScroll).toMatch(/overflow-y:\s*auto/);
    // Without `min-height: 0` a flex child refuses to shrink below its content,
    // so the overflow never engages and the scrollbar never appears.
    expect(cardScroll).toMatch(/min-height:\s*0/);
    expect(cardScroll).toMatch(/flex:\s*1/);
  });

  test('the column around it does not scroll instead', () => {
    // Two scrollbars, or the header scrolling away with the cards, both come
    // from the main column also being scrollable.
    const main = rule('main');
    expect(main).toMatch(/overflow:\s*hidden/);
    expect(main).toMatch(/min-width:\s*0/);
  });

  test('the header does not shrink when the list is long', async () => {
    const { container } = await renderSettled();
    const header = container.querySelector('header') as HTMLElement;
    expect(header.style.flexShrink).toBe('0');
  });
});
