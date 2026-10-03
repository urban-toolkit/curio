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
      ['Discovery Catalog', '/catalog/discovery'],
      ['Model Catalog', '/catalog/models'],
    ]);
  });

  test.each([
    ['/projects', 'Projects'],
    ['/catalog/nodes', 'Node Catalog'],
    ['/catalog/data', 'Data Catalog'],
    ['/catalog/discovery', 'Discovery Catalog'],
    ['/catalog/models', 'Model Catalog'],
  ])('%s marks exactly %s active', (path, label) => {
    const { container } = renderAt(path);
    expect(activeLabels(container)).toEqual([label]);
  });

  test('/monitor marks no tab active', () => {
    // Monitor is a top-bar link (globalPageHeader.test.tsx), not a section.
    const { container } = renderAt('/monitor');
    expect(activeLabels(container)).toEqual([]);
  });

  test('a dataset detail route keeps Data Catalog active', () => {
    // NavLink for /catalog/data is intentionally not `end` so nested detail
    // routes still light up their parent section.
    const { container } = renderAt('/catalog/data/some-dataset-id');
    expect(activeLabels(container)).toEqual(['Data Catalog']);
  });

  test('a portal detail route keeps Discovery Catalog active', () => {
    // Same reason the Data Catalog link is not `end`: /catalog/discovery/:sourceDir
    // is a page WITHIN that section, so the tab has to stay lit on it.
    const { container } = renderAt('/catalog/discovery/source.uk.data-gov@1');
    expect(activeLabels(container)).toEqual(['Discovery Catalog']);
  });

  test('a model detail route keeps Model Catalog active', () => {
    // /catalog/models/:modelId is the Model Catalog with that model's details
    // open, so its link is not `end` either.
    const { container } = renderAt('/catalog/models/model.curio.ddrnet23-slim');
    expect(activeLabels(container)).toEqual(['Model Catalog']);
  });
});
