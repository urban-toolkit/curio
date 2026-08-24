/**
 * The top-level Projects / Node Catalog / Data Catalog tabs.
 *
 * These replaced the old one-off header buttons (a small "Catalog" button on
 * /projects, a mirror-image "Projects" button on /catalog), so the strip is now
 * the only way to move between sections — worth pinning.
 */
import React from 'react';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import AppSectionTabs from '../../components/layout/AppSectionTabs';

/** identity-obj-proxy maps CSS modules to their own key names. */
const ACTIVE = 'tabLinkActive';

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppSectionTabs />
    </MemoryRouter>
  );
}

function activeLabels(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll(`.${ACTIVE}`)).map((el) =>
    (el.textContent || '').trim()
  );
}

describe('AppSectionTabs', () => {
  test('renders the three sections as sibling links', () => {
    const { getByRole } = renderAt('/projects');

    const nav = getByRole('navigation', { name: 'Main sections' });
    expect(
      Array.from(nav.querySelectorAll('a')).map((a) => [
        (a.textContent || '').trim(),
        a.getAttribute('href'),
      ])
    ).toEqual([
      ['Projects', '/projects'],
      ['Node Catalog', '/catalog/nodes'],
      ['Data Catalog', '/catalog/data'],
    ]);
  });

  test.each([
    ['/projects', 'Projects'],
    ['/catalog/nodes', 'Node Catalog'],
    ['/catalog/data', 'Data Catalog'],
  ])('%s marks exactly %s active', (path, label) => {
    const { container } = renderAt(path);
    expect(activeLabels(container)).toEqual([label]);
  });

  test('a dataset detail route keeps Data Catalog active', () => {
    // NavLink for /catalog/data is intentionally not `end` so nested detail
    // routes still light up their parent section.
    const { container } = renderAt('/catalog/data/some-dataset-id');
    expect(activeLabels(container)).toEqual(['Data Catalog']);
  });
});
