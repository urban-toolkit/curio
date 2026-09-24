import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { DataLakeCatalogBrowse } from '../../pages/dataLakes/DataLakeCatalogBrowse';
import { invalidateLakeCatalogCache } from '../../services/dataLakeCatalog';
import type { LakeCatalogResponse, LakeSourceRow } from '../../services/dataLakeCatalog';

jest.mock('../../utils/authApi', () => ({
  apiFetch: jest.fn(),
  getToken: jest.fn(() => 'token'),
}));

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { apiFetch } = require('../../utils/authApi') as { apiFetch: jest.Mock };

function source(over: Partial<LakeSourceRow> = {}): LakeSourceRow {
  return {
    sourceId: 'lake.a.portal',
    dirName: 'lake.a.portal@1',
    name: 'Alpha Portal',
    version: '1.0.0',
    description: 'Alpha datasets.',
    publisher: 'Alpha City',
    homepage: null,
    license: '',
    tags: ['alpha'],
    iconUrl: null,
    provider: 'socrata',
    baseUrl: 'https://alpha.example',
    auth: {
      mode: 'public', required: false, usesToken: false,
      secretId: null, present: false, helpUrl: null,
    },
    capabilities: {
      search: true, describe: true, download: true,
      formats: ['csv', 'geojson'], maxDownloadBytes: 67108864,
    },
    createdAt: null,
    updatedAt: null,
    ...over,
  };
}

const response = (sources: LakeSourceRow[]): LakeCatalogResponse => ({
  sources,
  facets: {
    provider: sources.reduce<Record<string, number>>((acc, s) => {
      acc[s.provider] = (acc[s.provider] ?? 0) + 1;
      return acc;
    }, {}),
    auth: {},
  },
});

/** The card for one source. Queries are scoped to it because a provider
 *  label legitimately appears three times on this page - the rail, the filter
 *  chip and the card - and an unscoped getByText would match all of them. */
function card(dirName: string): HTMLElement {
  const el = document.querySelector(`[data-lake-source="${dirName}"]`);
  if (!el) throw new Error(`no card for ${dirName}`);
  return el as HTMLElement;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/catalog/lakes']}>
      <DataLakeCatalogBrowse />
    </MemoryRouter>
  );
}

beforeEach(() => {
  invalidateLakeCatalogCache();
  apiFetch.mockReset();
});

describe('DataLakeCatalogBrowse', () => {
  test('lists the portals the roster returns', async () => {
    apiFetch.mockResolvedValue(
      response([source(), source({ sourceId: 'lake.b.other', dirName: 'lake.b.other@1', name: 'Beta Portal', provider: 'ckan' })])
    );
    renderPage();
    expect(await screen.findByText('Alpha Portal')).toBeInTheDocument();
    expect(screen.getByText('Beta Portal')).toBeInTheDocument();
  });

  test('a card shows its provider, publisher and the formats it can deliver', async () => {
    apiFetch.mockResolvedValue(response([source()]));
    renderPage();
    await screen.findByText('Alpha Portal');
    const tile = within(card('lake.a.portal@1'));
    expect(tile.getByText('Socrata')).toBeInTheDocument();
    expect(tile.getByText('Alpha City')).toBeInTheDocument();
    expect(tile.getByText('CSV · GEOJSON')).toBeInTheDocument();
  });

  test('a source that cannot be searched says so instead of offering a browse', async () => {
    apiFetch.mockResolvedValue(
      response([
        source({
          name: 'Direct URL',
          provider: 'direct',
          capabilities: { ...source().capabilities, search: false },
        }),
      ])
    );
    renderPage();
    await screen.findByText('Alpha datasets.');
    const tile = within(card('lake.a.portal@1'));
    expect(tile.getByText('Link only')).toBeInTheDocument();
    // "Browse datasets" would be a lie: there is nothing to browse.
    expect(tile.getByRole('button', { name: 'Open' })).toBeInTheDocument();
    expect(tile.queryByRole('button', { name: 'Browse datasets' })).toBeNull();
  });

  test('a token-needing source is marked, and not as an error', async () => {
    apiFetch.mockResolvedValue(
      response([
        source({
          auth: { mode: 'required-token', required: true, usesToken: true,
                  secretId: 'socrata.app-token', present: false, helpUrl: null },
        }),
      ])
    );
    renderPage();
    await screen.findByText('Alpha Portal');
    const tile = within(card('lake.a.portal@1'));
    expect(tile.getByText('Token needed')).toBeInTheDocument();
  });

  test('an empty roster explains itself rather than showing a blank grid', async () => {
    apiFetch.mockResolvedValue(response([]));
    renderPage();
    expect(
      await screen.findByText('This deployment has no data lake sources configured.')
    ).toBeInTheDocument();
  });

  test('a failed load surfaces the error and keeps a retry', async () => {
    apiFetch.mockRejectedValue(new Error('backend is down'));
    renderPage();
    expect(await screen.findByText('backend is down')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  test('it asks the backend to filter rather than filtering locally', async () => {
    // One implementation of "does this match", so the chips and the search box
    // cannot disagree with each other.
    apiFetch.mockResolvedValue(response([source()]));
    renderPage();
    await screen.findByText('Alpha Portal');
    expect(apiFetch).toHaveBeenCalledWith('/api/datalakes/catalog');
  });
});
