/**
 * A link-only source's page (Direct URL, #439): a link pasted in is
 * downloaded with the link as its resource id, and gets a row of its own.
 */
import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { DiscoverySourceDetail } from '../../pages/discovery/DiscoverySourceDetail';
import { linkTitle } from '../../pages/discovery/DiscoveryLinkForm';
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
  sourceId: 'source.curio.direct-url',
  dirName: 'source.curio.direct-url@1',
  name: 'Direct URL',
  version: '1.0.0',
  description: '',
  publisher: 'Curio',
  homepage: null,
  license: '',
  tags: [],
  iconUrl: null,
  provider: 'direct',
  baseUrl: '',
  auth: { mode: 'public', required: false, usesToken: false, secretId: null, present: false, helpUrl: null },
  capabilities: { search: false, describe: false, download: true, formats: ['csv', 'geojson'], maxDownloadBytes: 1 },
  kind: 'portal',
  resources: [],
  createdAt: null,
  updatedAt: null,
};

const LINK = 'https://data.example.org/files/bike%20lanes.geojson';

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/catalog/discovery/source.curio.direct-url@1']}>
      <DatasetDetailsProvider closeOnNavigate>
        <Routes>
          <Route path="/catalog/discovery/:sourceDir" element={<DiscoverySourceDetail />} />
        </Routes>
      </DatasetDetailsProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiFetch.mockReset();
  jest.useFakeTimers();
});
afterEach(() => jest.useRealTimers());
afterEach(resetDiscoveryAcquisitions);

test('a link names its file', () => {
  expect(linkTitle(LINK)).toBe('bike lanes.geojson');
  expect(linkTitle('https://data.example.org/')).toBe('https://data.example.org/');
});

test('the page takes a link and downloads it, with the link as the resource', async () => {
  apiFetch.mockImplementation((path: string) => {
    if (path.includes('/acquire')) return Promise.resolve({ jobId: 'j1', status: 'queued' });
    if (path.startsWith('/api/discovery/jobs/')) return Promise.resolve({ jobId: 'j1', status: 'running' });
    return Promise.resolve(source);
  });
  renderPage();
  await act(async () => {
    await jest.advanceTimersByTimeAsync(0);
  });
  expect(screen.queryByText(/has nothing to search/)).toBeNull();
  expect(screen.getByText('It downloads into your Data Catalog as CSV, GEOJSON.')).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText('Link to a file'), { target: { value: LINK } });
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await jest.advanceTimersByTimeAsync(0);
  });
  const acquire = apiFetch.mock.calls.find(([path]) => String(path).includes('/acquire'));
  expect(acquire?.[0]).toBe(
    `/api/discovery/sources/source.curio.direct-url%401/resources/${encodeURIComponent(LINK)}/acquire`,
  );
  expect(JSON.parse(String(acquire?.[1]?.body))).toEqual({ title: 'bike lanes.geojson' });
  expect(screen.getByText('bike lanes.geojson')).toBeInTheDocument();
});

test('a finished link offers its dataset, not a Download that does nothing', async () => {
  // A pasted link's row has no format of its own: what the file is, is known
  // once it has downloaded, and the row stands for that.
  apiFetch.mockImplementation((path: string) => {
    if (path.includes('/acquire')) return Promise.resolve({ jobId: 'j1', status: 'queued' });
    if (path.startsWith('/api/discovery/jobs/')) {
      return Promise.resolve({
        jobId: 'j1', status: 'completed', bytesRead: 10, totalBytes: 10, stageMessage: '', error: null,
        datasetId: 'imported.xlanes', dataset: { id: 'imported.xlanes', format: 'geojson' },
        alreadyPresent: false, unchanged: false, sourceId: 'source.curio.direct-url@1', resourceId: LINK,
      });
    }
    return Promise.resolve(source);
  });
  renderPage();
  await act(async () => {
    await jest.advanceTimersByTimeAsync(0);
  });
  fireEvent.change(screen.getByLabelText('Link to a file'), { target: { value: LINK } });
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await jest.advanceTimersByTimeAsync(0);
  });
  await act(async () => {
    await jest.advanceTimersByTimeAsync(1000);
  });
  const row = document.querySelector(`[data-discovery-resource="${LINK}"]`) as HTMLElement;
  expect(row).not.toBeNull();
  expect(within(row).queryByRole('progressbar')).toBeNull();
  expect(within(row).getByRole('button', { name: 'View dataset' })).toBeInTheDocument();
  expect(within(row).queryByRole('button', { name: 'Download' })).toBeNull();
});

test('a GeoParquet link takes an Area and sends it, and another link asks none (#608)', async () => {
  const withArea: DiscoverySourceRow = {
    ...source,
    capabilities: { ...source.capabilities, formats: ['csv', 'geojson', 'parquet'] },
    parameters: [
      { id: 'area', type: 'area', label: 'Area', description: 'Keep only the rows inside a box.', required: false, accepts: ['box'] },
    ],
  };
  const parquet = 'https://data.example.org/files/blocks.parquet';
  apiFetch.mockImplementation((path: string) => {
    if (path.includes('/acquire')) return Promise.resolve({ jobId: 'j1', status: 'queued' });
    if (path.startsWith('/api/discovery/jobs/')) {
      return Promise.resolve({
        jobId: 'j1', status: 'completed', bytesRead: 10, totalBytes: 10, stageMessage: '', error: null,
        datasetId: 'imported.xblocks',
        dataset: { id: 'imported.xblocks', format: 'parquet', discoverySource: { parametersHash: 'h1' } },
        alreadyPresent: false, unchanged: false, sourceId: 'source.curio.direct-url@1', resourceId: parquet,
      });
    }
    return Promise.resolve(withArea);
  });
  renderPage();
  await act(async () => {
    await jest.advanceTimersByTimeAsync(0);
  });
  fireEvent.change(screen.getByLabelText('Link to a file'), { target: { value: LINK } });
  expect(screen.queryByRole('group', { name: 'Area' })).toBeNull();

  fireEvent.change(screen.getByLabelText('Link to a file'), { target: { value: parquet } });
  const area = screen.getByRole('group', { name: 'Area' });
  fireEvent.click(within(area).getByRole('tab', { name: 'Coordinates' }));
  ['-87.64', '41.87', '-87.62', '41.89'].forEach((value, i) => {
    fireEvent.change(within(area).getByLabelText(['West', 'South', 'East', 'North'][i]), { target: { value } });
  });
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await jest.advanceTimersByTimeAsync(0);
  });
  const acquire = apiFetch.mock.calls.find(([path]) => String(path).includes('/acquire'));
  expect(acquire?.[0]).toBe(
    `/api/discovery/sources/source.curio.direct-url%401/resources/${encodeURIComponent(parquet)}/acquire`,
  );
  // Named by the server after the file and the area, so it is told apart
  // from the whole file.
  expect(JSON.parse(String(acquire?.[1]?.body))).toEqual({
    parameters: { area: { box: [-87.64, 41.87, -87.62, 41.89] } },
  });
  // The part that landed is what the link's row offers, as a whole file is.
  await act(async () => {
    await jest.advanceTimersByTimeAsync(1000);
  });
  const row = document.querySelector(`[data-discovery-resource="${parquet}"]`) as HTMLElement;
  expect(row).not.toBeNull();
  expect(within(row).getByRole('button', { name: 'View dataset' })).toBeInTheDocument();
  expect(within(row).queryByRole('button', { name: 'Download' })).toBeNull();
});

test('a link that is not https is refused before any request', async () => {
  apiFetch.mockResolvedValue(source);
  renderPage();
  await act(async () => {
    await jest.advanceTimersByTimeAsync(0);
  });
  fireEvent.change(screen.getByLabelText('Link to a file'), { target: { value: 'http://data.example.org/a.csv' } });
  expect(screen.getByText('The link must start with https://.')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Download' })).toBeDisabled();
  expect(apiFetch.mock.calls.some(([path]) => String(path).includes('/acquire'))).toBe(false);
});
