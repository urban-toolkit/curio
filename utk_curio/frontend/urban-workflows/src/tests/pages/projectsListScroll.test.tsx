/**
 * Regression test for #161 — the projects page had no scrollbar.
 *
 * MainCanvas.css sets `html, body { overflow: hidden }` and, being a plain
 * (non-module) import in a statically-imported component, style-loader injects
 * it for every route. ProjectsList used `minHeight: 100vh` and relied on
 * document scroll, so once the grid passed the viewport the rest was
 * unreachable. The catalog pages already solve this by owning their scroll
 * within the viewport; this pins ProjectsList to the same shape.
 */
import React from 'react';
import { render, act } from '@testing-library/react';

jest.mock('../../providers/UserProvider', () => ({
  useUserContext: () => ({ user: { name: 'Test User' }, signout: jest.fn(), enableUserAuth: false }),
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
jest.mock('react-router-dom', () => ({
  useNavigate: () => jest.fn(),
  Link: ({ children }: any) => <a>{children}</a>,
}));
jest.mock('assets/curio-2.png', () => 'logo.png');

import ProjectsList from '../../pages/projects/ProjectsList';

/** Render and let the initial projectsApi.list() promise settle. */
async function renderSettled() {
  let utils: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<ProjectsList />);
  });
  return utils!;
}

describe('ProjectsList scroll ownership', () => {
  test('the main region scrolls inside a viewport-bounded shell', async () => {
    const { container } = await renderSettled();

    const page = container.firstElementChild as HTMLElement;
    // Bounded height, not minHeight: with html/body overflow hidden, a page that
    // merely grows past the viewport just gets clipped.
    expect(page.style.height).toBe('100vh');
    expect(page.style.overflow).toBe('hidden');
    expect(page.style.display).toBe('flex');
    expect(page.style.flexDirection).toBe('column');

    const main = container.querySelector('[data-curio-projects-scroll="true"]') as HTMLElement;
    expect(main).not.toBeNull();
    expect(main.style.overflowY).toBe('auto');
    // Without `min-height: 0` a flex child refuses to shrink below its content,
    // so the overflow never engages and the scrollbar never appears.
    expect(main.style.minHeight).toBe('0px');
    expect(main.style.flex).toContain('1');
  });

  test('the header does not shrink when the list is long', async () => {
    const { container } = await renderSettled();
    const header = container.querySelector('header') as HTMLElement;
    expect(header.style.flexShrink).toBe('0');
  });
});
