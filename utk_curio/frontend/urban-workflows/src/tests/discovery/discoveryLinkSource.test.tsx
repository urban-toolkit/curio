/**
 * A link-only source's page (Direct URL, #439): a link pasted in is
 * downloaded with the link as its resource id, and gets a row of its own.
 */
import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
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
