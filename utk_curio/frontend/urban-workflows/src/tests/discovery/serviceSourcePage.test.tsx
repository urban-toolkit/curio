/**
 * A service source's page (OpenStreetMap): the resources its manifest
 * declares, each downloaded once its questions are answered, and named after
 * the place it covers unless the person names it.
 */
import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { DiscoverySourceDetail } from '../../pages/discovery/DiscoverySourceDetail';
import { resetDiscoveryAcquisitions } from '../../services/discoveryCatalog/discoveryCatalogHooks';
import { DatasetDetailsProvider } from '../../components/datasets/catalog/DatasetDetailsProvider';
import {
  DISCOVERY_PROVIDER_LABEL,
  downloadBody,
  isServiceSource,
  type DiscoverySourceRow,
} from '../../services/discoveryCatalog';
import { PROVIDER_FILTERS } from '../../pages/discovery/discoveryBrowseConstants';

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

const AREA = {
  id: 'area', type: 'area', label: 'Area', description: '', required: true, accepts: ['names'],
};

const source: DiscoverySourceRow = {
  sourceId: 'source.osm.openstreetmap',
  dirName: 'source.osm.openstreetmap@1',
  name: 'OpenStreetMap',
  version: '1.0.0',
  description: '',
  publisher: 'OpenStreetMap contributors',
  homepage: 'https://www.openstreetmap.org',
  license: 'ODbL 1.0',
  tags: [],
  iconUrl: null,
  provider: 'autark-osm',
  baseUrl: 'https://overpass-api.de',
  auth: { mode: 'public', required: false, usesToken: false, secretId: null, present: false, helpUrl: null },
  capabilities: { search: true, describe: true, download: true, formats: ['geojson'], maxDownloadBytes: 1 },
  kind: 'service',
  resources: [],
  createdAt: null,
  updatedAt: null,
};

const parks = {
  sourceId: source.sourceId,
  sourceName: source.name,
  resourceId: 'parks',
  name: 'Parks',
  description: 'Parks, gardens, woods and other green space.',
  publisher: 'OpenStreetMap contributors',
  formats: ['geojson'],
  updatedAt: null,
  landingUrl: null,
  sizeHint: null,
  acquirable: true,
  alreadyHeldDatasetId: null,
  heldFormats: {},
  parameters: [AREA],
  kind: 'table',
  fileCount: null,
  fieldValues: [],
  samples: [],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/catalog/discovery/source.osm.openstreetmap@1']}>
      <DatasetDetailsProvider closeOnNavigate>
        <Routes>
          <Route path="/catalog/discovery/:sourceDir" element={<DiscoverySourceDetail />} />
        </Routes>
      </DatasetDetailsProvider>
    </MemoryRouter>,
  );
}

function serve(acquireAnswer = { jobId: 'j1', status: 'queued' }) {
  apiFetch.mockImplementation((path: string) => {
    if (path.includes('/acquire')) return Promise.resolve(acquireAnswer);
    if (path.startsWith('/api/discovery/jobs/')) return Promise.resolve({ jobId: 'j1', status: 'running' });
    if (path.includes('/search')) {
      return Promise.resolve({
        resources: [parks],
        sources: [{ sourceId: source.sourceId, status: 'ok', count: 1 }],
        nextCursor: null,
        totalHint: null,
        truncated: false,
      });
    }
    return Promise.resolve(source);
  });
}

async function settle() {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(0);
  });
  await act(async () => {
    await jest.advanceTimersByTimeAsync(400);
  });
}

function acquireCall() {
  return apiFetch.mock.calls.find(([path]) => String(path).includes('/acquire'));
}

beforeEach(() => {
  apiFetch.mockReset();
  jest.useFakeTimers();
});
afterEach(() => jest.useRealTimers());
afterEach(resetDiscoveryAcquisitions);

test('a service is its own kind of source, with a label and a filter chip', () => {
  expect(isServiceSource(source)).toBe(true);
  expect(isServiceSource({ kind: 'storage' })).toBe(false);
  expect(DISCOVERY_PROVIDER_LABEL['autark-osm']).toBe('OpenStreetMap (Autark)');
  expect(PROVIDER_FILTERS.map((f) => f.value)).toContain('autark-osm');
});

test('a download is named after the row for a portal, and after the place for a service', () => {
  expect(downloadBody({ kind: 'portal' }, { name: 'Crimes' }, 'csv')).toEqual({ format: 'csv', title: 'Crimes' });
  expect(downloadBody(source, { name: 'Parks' }, 'geojson', { area: 1 })).toEqual({
    format: 'geojson',
    parameters: { area: 1 },
  });
  expect(downloadBody(source, { name: 'Parks' }, 'geojson', undefined, '  Golf parks ')).toEqual({
    format: 'geojson',
    title: 'Golf parks',
  });
});

test('the page lists the declared resources, and Download asks for the area first', async () => {
  serve();
  renderPage();
  await settle();
  const row = document.querySelector('[data-discovery-resource="parks"]') as HTMLElement;
  expect(within(row).getByText('Parks')).toBeInTheDocument();
  // The source's own page links its homepage; the row does not repeat it as a portal page.
  expect(within(row).queryByText(/View on the portal/)).toBeNull();

  fireEvent.click(within(row).getByRole('button', { name: 'Download' }));
  expect(acquireCall()).toBeUndefined();
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByText('Area is needed.')).toBeInTheDocument();
  const name = within(dialog).getByLabelText('Name in your Data Catalog') as HTMLInputElement;
  expect(name.value).toBe('');
  expect(name.placeholder).toBe('Parks, and the place it covers');
});

test('the area is named areas inside a place, and no title is sent unless typed', async () => {
  serve();
  renderPage();
  await settle();
  const row = document.querySelector('[data-discovery-resource="parks"]') as HTMLElement;
  fireEvent.click(within(row).getByRole('button', { name: 'Download' }));
  const dialog = screen.getByRole('dialog');
  // Names are the only form this source takes, so there are no tabs to pick from.
  expect(within(dialog).queryByRole('tab')).toBeNull();

  apiFetch.mockImplementationOnce(() =>
    Promise.resolve({ places: [{ name: 'Golf', label: 'Golf, Cook County, Illinois', box: [-87.8, 42.05, -87.78, 42.06], kind: 'boundary/administrative', boundary: true }] }),
  );
  fireEvent.change(within(dialog).getByPlaceholderText(/A city or region/), { target: { value: 'Illinois' } });
  fireEvent.change(within(dialog).getByPlaceholderText(/A neighbourhood or district/), { target: { value: 'Golf' } });
  await act(async () => {
    fireEvent.click(within(dialog).getByRole('button', { name: 'Search' }));
    await jest.advanceTimersByTimeAsync(0);
  });
  fireEvent.click(within(dialog).getByRole('button', { name: /^Golf/ }));
  await act(async () => {
    fireEvent.click(within(dialog).getByRole('button', { name: 'Download' }));
    await jest.advanceTimersByTimeAsync(0);
  });

  const call = acquireCall();
  expect(call?.[0]).toBe('/api/discovery/sources/source.osm.openstreetmap%401/resources/parks/acquire');
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    format: 'geojson',
    parameters: { area: { names: { geocodeArea: 'Illinois', areas: ['Golf'] } } },
  });
});
