import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { DataLakeCatalogBrowse } from '../../pages/dataLakes/DataLakeCatalogBrowse';
import { invalidateLakeCatalogCache } from '../../services/dataLakeCatalog';
import type { LakeCatalogResponse, LakeSourceRow } from '../../services/dataLakeCatalog';

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

function renderPage(entry = '/catalog/lakes') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <DataLakeCatalogBrowse />
    </MemoryRouter>
  );
}

const searchResponse = (over: Record<string, unknown> = {}) => ({
  resources: [],
  sources: [],
  nextCursor: null,
  totalHint: null,
  truncated: false,
  ...over,
});

const resourceRow = (over: Record<string, unknown> = {}) => ({
  sourceId: 'lake.a.portal',
  sourceName: 'Alpha Portal',
  resourceId: 'abcd-1234',
  name: 'Bike Routes',
  description: '',
  publisher: 'Alpha City',
  formats: ['geojson'],
  updatedAt: null,
  landingUrl: null,
  sizeHint: null,
  acquirable: true,
  alreadyHeldDatasetId: null,
  ...over,
});

/** Route the mocked client by path, so one test can serve both the roster and
 *  a search without caring which order the page asks in. */
function routeApi(handlers: Record<string, unknown>) {
  apiFetch.mockImplementation((path: string) => {
    for (const [fragment, value] of Object.entries(handlers)) {
      if (path.includes(fragment)) return Promise.resolve(value);
    }
    return Promise.reject(new Error(`unexpected call: ${path}`));
  });
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
    expect(await screen.findAllByText('Alpha Portal')).not.toHaveLength(0);
    expect(screen.getByText('Beta Portal')).toBeInTheDocument();
  });

  test('a card shows its provider, publisher and the formats it can deliver', async () => {
    apiFetch.mockResolvedValue(response([source()]));
    renderPage();
    await screen.findAllByText('Alpha Portal');
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
    await screen.findAllByText('Alpha datasets.');
    const tile = within(card('lake.a.portal@1'));
    expect(tile.getByText('Link only')).toBeInTheDocument();
    // "Browse datasets" would be a lie: there is nothing to browse. The card
    // offers what the drawer offers, and the drawer offers no browse here.
    expect(tile.queryByRole('button', { name: 'Browse datasets' })).toBeNull();
    expect(tile.queryByRole('button', { name: 'Open' })).toBeNull();
    expect(tile.getByRole('button', { name: 'View details' })).toBeInTheDocument();
  });

  test('a source that needs a token it does not have offers no browse either', async () => {
    // The drawer already said "needs a token before it can be searched" while
    // the card beside it offered Browse datasets.
    apiFetch.mockResolvedValue(
      response([
        source({
          auth: { mode: 'required-token', required: true, usesToken: true,
                  secretId: 'socrata.app-token', present: false, helpUrl: null },
        }),
      ])
    );
    renderPage();
    await screen.findAllByText('Alpha datasets.');
    const tile = within(card('lake.a.portal@1'));
    expect(tile.queryByRole('button', { name: 'Browse datasets' })).toBeNull();
    expect(tile.getByRole('button', { name: 'View details' })).toBeInTheDocument();
  });

  test('the drawer opens on the first source, as on the other catalog pages', async () => {
    apiFetch.mockResolvedValue(
      response([source(), source({ sourceId: 'lake.b.other', dirName: 'lake.b.other@1', name: 'Beta Portal' })])
    );
    renderPage();
    await screen.findAllByText('Beta Portal');
    const drawer = document.querySelector('[data-curio-drawer-ctas]') as HTMLElement;
    expect(drawer).not.toBeNull();
    expect(within(drawer).getByRole('button', { name: 'Browse datasets' })).toBeInTheDocument();
    expect(card('lake.a.portal@1').className).toMatch(/cardActive/);
  });

  test('a closed drawer stays closed', async () => {
    apiFetch.mockResolvedValue(response([source()]));
    renderPage();
    await screen.findAllByText('Alpha datasets.');
    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(document.querySelector('[data-curio-drawer-ctas]')).toBeNull();
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
    await screen.findAllByText('Alpha Portal');
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
    await screen.findAllByText('Alpha Portal');
    expect(apiFetch).toHaveBeenCalledWith('/api/datalakes/catalog');
  });
});


describe('DataLakeCatalogBrowse: federated search mode', () => {
  test('a query in the URL swaps the card grid for portal results', async () => {
    routeApi({
      '/catalog': response([source()]),
      '/api/datalakes/search': searchResponse({
        resources: [resourceRow(), resourceRow({ resourceId: 'x', name: 'Cycle Parking' })],
        sources: [{ sourceId: 'lake.a.portal', status: 'ok', count: 2 }],
      }),
    });
    renderPage('/catalog/lakes?q=bike');
    expect(await screen.findByText('Bike Routes')).toBeInTheDocument();
    expect(screen.getByText('Cycle Parking')).toBeInTheDocument();
    // The source CARDS are gone while results are showing.
    expect(document.querySelector('[data-lake-source]')).toBeNull();
  });

  test('each result is tagged with the portal it came from', async () => {
    routeApi({
      '/catalog': response([source()]),
      '/api/datalakes/search': searchResponse({
        resources: [resourceRow()],
        sources: [{ sourceId: 'lake.a.portal', status: 'ok' }],
      }),
    });
    renderPage('/catalog/lakes?q=bike');
    await screen.findByText('Bike Routes');
    const row = document.querySelector('[data-lake-resource]') as HTMLElement;
    expect(row).not.toBeNull();
    expect(within(row).getByText('Alpha Portal')).toBeInTheDocument();
  });

  test('a portal that did not answer is named, and the rest still render', async () => {
    // The property that matters: one portal having a bad afternoon must not
    // empty the page.
    routeApi({
      '/catalog': response([
        source(),
        source({ sourceId: 'lake.b.other', dirName: 'lake.b.other@1', name: 'Beta Portal' }),
      ]),
      '/api/datalakes/search': searchResponse({
        resources: [resourceRow()],
        sources: [
          { sourceId: 'lake.a.portal', status: 'ok' },
          { sourceId: 'lake.b.other', status: 'failed', detail: 'timed out' },
        ],
      }),
    });
    renderPage('/catalog/lakes?q=bike');
    expect(await screen.findByText(/Beta Portal did not answer/)).toBeInTheDocument();
    expect(screen.getByText('Bike Routes')).toBeInTheDocument();
  });

  test('a link-only source reporting unsupported is not called a failure', async () => {
    routeApi({
      '/catalog': response([source()]),
      '/api/datalakes/search': searchResponse({
        resources: [resourceRow()],
        sources: [
          { sourceId: 'lake.a.portal', status: 'ok' },
          { sourceId: 'lake.curio.direct-url', status: 'unsupported' },
        ],
      }),
    });
    renderPage('/catalog/lakes?q=bike');
    await screen.findByText('Bike Routes');
    expect(screen.queryByText(/did not answer/)).toBeNull();
  });

  test('no matches anywhere says so', async () => {
    routeApi({
      '/catalog': response([source()]),
      '/api/datalakes/search': searchResponse({
        sources: [{ sourceId: 'lake.a.portal', status: 'ok', count: 0 }],
      }),
    });
    renderPage('/catalog/lakes?q=nothing');
    expect(
      await screen.findByText(/No portal returned anything/)
    ).toBeInTheDocument();
  });

  test('the roster is not filtered by the search text', async () => {
    // That text is a question for the portals, not for the roster - the rail
    // counts and the source names beside results both come from the roster.
    routeApi({
      '/catalog': response([source()]),
      '/api/datalakes/search': searchResponse({ sources: [] }),
    });
    renderPage('/catalog/lakes?q=bike');
    await screen.findByText(/No portal returned anything/);
    const rosterCalls = apiFetch.mock.calls
      .map((c) => c[0])
      .filter((p) => p.includes('/datalakes/catalog'));
    expect(rosterCalls.every((p) => !p.includes('q='))).toBe(true);
  });
});
