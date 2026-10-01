import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { DiscoveryCatalogBrowse } from '../../pages/discovery/DiscoveryCatalogBrowse';
import { invalidateDiscoveryCatalogCache } from '../../services/discoveryCatalog';
import type { DiscoverySourceRow } from '../../services/discoveryCatalog';

/**
 * A Discovery Catalog source has a details view, the same shape as the other three
 * catalogs'.
 *
 * It had none. The card's one button browsed the portal, the drawer was the
 * only place a source's endpoint, licence, formats and token help appeared, and
 * below 1100px that drawer column is hidden, so none of it could be read. The
 * Node, Data and Agent pages each open a details modal from the card, from the
 * drawer and from the right-click menu, and so does this one now.
 */

jest.mock('../../utils/authApi', () => ({
  apiFetch: jest.fn(),
  getToken: jest.fn(() => 'token'),
}));

// A finished download raises a toast; which toast is asserted where a download
// finishes, not here.
jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { apiFetch } = require('../../utils/authApi') as { apiFetch: jest.Mock };

const source = (over: Partial<DiscoverySourceRow> = {}): DiscoverySourceRow => ({
  sourceId: 'source.a.portal',
  dirName: 'source.a.portal@1',
  name: 'Alpha Portal',
  version: '1.0.0',
  description: 'Alpha datasets.',
  publisher: 'Alpha City',
  homepage: 'https://alpha.example/',
  license: 'ODbL',
  tags: ['transport'],
  iconUrl: null,
  provider: 'socrata',
  baseUrl: 'https://api.alpha.example',
  auth: {
    mode: 'public', required: false, usesToken: false,
    secretId: null, present: false, helpUrl: null,
  },
  capabilities: {
    search: true, describe: true, download: true,
    formats: ['csv', 'geojson'], maxDownloadBytes: 67108864,
  },
  kind: 'portal',
  resources: [],
  createdAt: null,
  updatedAt: null,
  ...over,
});

const linkOnly = source({
  sourceId: 'source.b.direct',
  dirName: 'source.b.direct@1',
  name: 'Direct URL',
  provider: 'direct',
  baseUrl: '',
  homepage: null,
  capabilities: { ...source().capabilities, search: false },
});

let location = '';
const LocationProbe: React.FC = () => {
  const loc = useLocation();
  location = loc.pathname;
  return null;
};

function renderPage() {
  apiFetch.mockImplementation((path: string) =>
    path.includes('/api/discovery/catalog')
      ? Promise.resolve({
          sources: [source(), linkOnly],
          facets: { provider: { socrata: 1, direct: 1 }, auth: {} },
        })
      : Promise.reject(new Error(`unexpected call: ${path}`))
  );
  return render(
    <MemoryRouter initialEntries={['/catalog/discovery']}>
      <Routes>
        <Route path="/catalog/discovery" element={<DiscoveryCatalogBrowse />} />
        <Route path="/catalog/discovery/:sourceDir" element={<p>Portal page</p>} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>
  );
}

async function card(dirName: string): Promise<HTMLElement> {
  await screen.findAllByText('Alpha Portal');
  const el = document.querySelector(`[data-discovery-source="${dirName}"]`);
  if (!el) throw new Error(`no card for ${dirName}`);
  return el as HTMLElement;
}

const detailsDialog = () => screen.getByRole('dialog', { name: 'Source details' });

beforeEach(() => {
  invalidateDiscoveryCatalogCache();
  apiFetch.mockReset();
  location = '';
});

describe('a Discovery Catalog source has a details view', () => {
  test("the card's View details opens it, and the page stays", async () => {
    renderPage();
    fireEvent.click(
      within(await card('source.a.portal@1')).getByRole('button', { name: 'View details' })
    );

    const dialog = detailsDialog();
    expect(within(dialog).getByRole('heading', { name: 'Alpha Portal' })).toBeInTheDocument();
    expect(location).toBe('/catalog/discovery');
  });

  test('it shows what only the drawer used to show', async () => {
    renderPage();
    fireEvent.click(
      within(await card('source.a.portal@1')).getByRole('button', { name: 'View details' })
    );

    const dialog = within(detailsDialog());
    expect(dialog.getByText('https://api.alpha.example')).toBeInTheDocument();
    expect(dialog.getByText('ODbL')).toBeInTheDocument();
    expect(dialog.getByText('CSV, GEOJSON')).toBeInTheDocument();
    expect(dialog.getByText('64 MB')).toBeInTheDocument();
    expect(dialog.getByText('source.a.portal')).toBeInTheDocument();
    // An external link says so.
    expect(dialog.getByRole('link', { name: 'alpha.example ↗' })).toHaveAttribute(
      'target',
      '_blank'
    );
  });

  test("the drawer's View details opens the same modal", async () => {
    renderPage();
    fireEvent.click(await card('source.a.portal@1'));
    const drawer = document.querySelector('[data-curio-drawer-ctas]') as HTMLElement;
    expect(within(drawer).getByRole('button', { name: 'Browse datasets' })).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole('button', { name: 'View details' }));

    expect(within(detailsDialog()).getByRole('heading', { name: 'Alpha Portal' })).toBeInTheDocument();
  });

  test('its Browse datasets goes to the portal page', async () => {
    renderPage();
    fireEvent.click(
      within(await card('source.a.portal@1')).getByRole('button', { name: 'View details' })
    );
    fireEvent.click(within(detailsDialog()).getByRole('button', { name: 'Browse datasets' }));

    expect(location).toBe('/catalog/discovery/source.a.portal%401');
    expect(screen.getByText('Portal page')).toBeInTheDocument();
  });

  test('a source with nothing to browse says why instead of offering it', async () => {
    renderPage();
    fireEvent.click(
      within(await card('source.b.direct@1')).getByRole('button', { name: 'View details' })
    );

    const dialog = within(detailsDialog());
    expect(dialog.queryByRole('button', { name: 'Browse datasets' })).toBeNull();
    expect(dialog.getByText(/has nothing to browse/)).toBeInTheDocument();
  });

  test('closing it leaves the page as it was', async () => {
    renderPage();
    fireEvent.click(
      within(await card('source.a.portal@1')).getByRole('button', { name: 'View details' })
    );
    fireEvent.click(within(detailsDialog()).getByRole('button', { name: 'Close' }));

    expect(screen.queryByRole('dialog', { name: 'Source details' })).toBeNull();
    expect(location).toBe('/catalog/discovery');
  });
});

describe('a Discovery Catalog card answers a right-click', () => {
  test("with the drawer's primary action, then View details", async () => {
    renderPage();
    fireEvent.contextMenu(await card('source.a.portal@1'));

    const menu = screen.getByRole('menu', { name: 'Source actions' });
    expect(within(menu).getAllByRole('menuitem').map((item) => item.textContent)).toEqual([
      'Browse datasets',
      'View details',
    ]);
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'View details' }));
    expect(within(detailsDialog()).getByRole('heading', { name: 'Alpha Portal' })).toBeInTheDocument();
  });

  test('a source with nothing to browse offers only its details', async () => {
    renderPage();
    fireEvent.contextMenu(await card('source.b.direct@1'));

    const menu = screen.getByRole('menu', { name: 'Source actions' });
    expect(within(menu).getAllByRole('menuitem').map((item) => item.textContent)).toEqual([
      'View details',
    ]);
  });

  test('Browse datasets from the menu goes to the portal page', async () => {
    renderPage();
    fireEvent.contextMenu(await card('source.a.portal@1'));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Browse datasets' }));

    expect(location).toBe('/catalog/discovery/source.a.portal%401');
  });
});
