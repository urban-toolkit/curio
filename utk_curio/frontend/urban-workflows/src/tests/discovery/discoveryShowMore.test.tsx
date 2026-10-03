/**
 * A portal's page lists the first page of what matches, and **Show more**
 * asks the portal for the next one. It used to list the first 20 matches and
 * offer no way to reach the rest.
 */
import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { DiscoverySourceDetail } from '../../pages/discovery/DiscoverySourceDetail';
import { resetDiscoveryAcquisitions } from '../../services/discoveryCatalog/discoveryCatalogHooks';
import { DatasetDetailsProvider } from '../../components/datasets/catalog/DatasetDetailsProvider';
import type { DiscoverySourceRow } from '../../services/discoveryCatalog';

jest.mock('../../utils/authApi', () => ({
  apiFetch: jest.fn(),
  getToken: jest.fn(() => 'token'),
}));
jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
// The details modal pulls in the chart stack; this page only opens it.
jest.mock('../../components/datasets/catalog/DatasetDetailModal', () => ({
  DatasetDetailModal: () => null,
}));

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { apiFetch } = require('../../utils/authApi') as { apiFetch: jest.Mock };

const source: DiscoverySourceRow = {
  sourceId: 'source.saopaulo.geosampa',
  dirName: 'source.saopaulo.geosampa@1',
  name: 'GeoSampa',
  version: '1.0.0',
  description: '',
  publisher: 'Prefeitura de São Paulo',
  homepage: 'https://geosampa.prefeitura.sp.gov.br',
  license: '',
  tags: [],
  iconUrl: null,
  provider: 'wfs',
  baseUrl: 'https://wms.geosampa.prefeitura.sp.gov.br/geoserver/ows',
  auth: { mode: 'public', required: false, usesToken: false, secretId: null, present: false, helpUrl: null },
  capabilities: { search: true, describe: true, download: true, formats: ['geojson'], maxDownloadBytes: 1 },
  kind: 'portal',
  resources: [],
  createdAt: null,
  updatedAt: null,
};

const layer = (resourceId: string) => ({
  sourceId: source.sourceId,
  sourceName: source.name,
  resourceId,
  name: resourceId,
  description: '',
  publisher: source.publisher,
  formats: ['geojson'],
  updatedAt: null,
  landingUrl: null,
  sizeHint: null,
  acquirable: true,
  alreadyHeldDatasetId: null,
  heldFormats: {},
  parameters: [],
  kind: null,
  fileCount: null,
  fieldValues: [],
  samples: [],
});

function serve() {
  apiFetch.mockImplementation((path: string) => {
    if (path.includes('/search')) {
      const next = path.includes('cursor=2');
      return Promise.resolve({
        resources: next ? [layer('geoportal:c')] : [layer('geoportal:a'), layer('geoportal:b')],
        sources: [{ sourceId: source.sourceId, status: 'ok', count: 2 }],
        nextCursor: next ? null : '2',
        totalHint: 3,
        truncated: false,
      });
    }
    return Promise.resolve(source);
  });
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/catalog/discovery/source.saopaulo.geosampa@1?q=onibus']}>
      <DatasetDetailsProvider closeOnNavigate>
        <Routes>
          <Route path="/catalog/discovery/:sourceDir" element={<DiscoverySourceDetail />} />
        </Routes>
      </DatasetDetailsProvider>
    </MemoryRouter>,
  );
}

async function settle() {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(0);
  });
  await act(async () => {
    await jest.advanceTimersByTimeAsync(400);
  });
}

const rows = () =>
  Array.from(document.querySelectorAll('[data-discovery-resource]')).map((el) =>
    el.getAttribute('data-discovery-resource'),
  );

beforeEach(() => {
  apiFetch.mockReset();
  jest.useFakeTimers();
});
afterEach(() => jest.useRealTimers());
afterEach(resetDiscoveryAcquisitions);

test('Show more adds the next page of matches below the first, then goes away', async () => {
  serve();
  renderPage();
  await settle();
  expect(rows()).toEqual(['geoportal:a', 'geoportal:b']);

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Show more' }));
    await jest.advanceTimersByTimeAsync(0);
  });
  expect(rows()).toEqual(['geoportal:a', 'geoportal:b', 'geoportal:c']);
  const asked = apiFetch.mock.calls.map(([path]) => String(path)).filter((path) => path.includes('/search'));
  expect(asked).toHaveLength(2);
  expect(asked[1]).toContain('cursor=2');
  expect(asked[1]).toContain('q=onibus');
  expect(screen.queryByRole('button', { name: 'Show more' })).toBeNull();
});

test('a portal whose first page is all there is offers no Show more', async () => {
  apiFetch.mockImplementation((path: string) =>
    path.includes('/search')
      ? Promise.resolve({
          resources: [layer('geoportal:a')],
          sources: [{ sourceId: source.sourceId, status: 'ok', count: 1 }],
          nextCursor: null,
          totalHint: 1,
          truncated: false,
        })
      : Promise.resolve(source),
  );
  renderPage();
  await settle();
  expect(rows()).toEqual(['geoportal:a']);
  expect(screen.queryByRole('button', { name: 'Show more' })).toBeNull();
});
