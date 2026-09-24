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
  test('renders the six sections as sibling links', () => {
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
      ['Agent Catalog', '/catalog/agents'],
      ['Data Lake Catalog', '/catalog/lakes'],
      ['Monitor', '/monitor'],
    ]);
  });

  test.each([
    ['/projects', 'Projects'],
    ['/catalog/nodes', 'Node Catalog'],
    ['/catalog/data', 'Data Catalog'],
    ['/catalog/lakes', 'Data Lake Catalog'],
    ['/monitor', 'Monitor'],
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

  test('a portal detail route keeps Data Lake Catalog active', () => {
    // Same reason the Data Catalog link is not `end`: /catalog/lakes/:sourceDir
    // is a page WITHIN that section, so the tab has to stay lit on it.
    const { container } = renderAt('/catalog/lakes/lake.uk.data-gov@1');
    expect(activeLabels(container)).toEqual(['Data Lake Catalog']);
  });

  test('the Monitor tab is unconditional', () => {
    // It is deliberately not gated on deploy mode: the monitor exists on every
    // instance. This renders with no provider at all, so if someone later
    // gates the tab on context state, this fails rather than silently hiding
    // the page on a laptop.
    const { getByRole } = renderAt('/projects');
    const nav = getByRole('navigation', { name: 'Main sections' });
    expect(
      Array.from(nav.querySelectorAll('a')).some(
        (a) => a.getAttribute('href') === '/monitor'
      )
    ).toBe(true);
  });
});
