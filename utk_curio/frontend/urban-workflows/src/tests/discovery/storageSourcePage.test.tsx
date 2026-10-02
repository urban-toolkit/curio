/**
 * A storage source's page: its declared resources as its last scan found
 * them, a scan followed until it ends, the files no resource declares, and
 * Rescan.
 */
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { DiscoverySourceDetail } from '../../pages/discovery/DiscoverySourceDetail';
import { resetDiscoveryAcquisitions } from '../../services/discoveryCatalog/discoveryCatalogHooks';
import { DatasetDetailsProvider } from '../../components/datasets/catalog/DatasetDetailsProvider';
import type { DiscoverySourceRow } from '../../services/discoveryCatalog';

jest.mock('../../utils/authApi', () => ({
  apiFetch: jest.fn(),
  getToken: jest.fn(() => 'token'),
}));
const mockShowToast = jest.fn();
jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
// The details modal pulls in the chart stack; this page only opens it.
jest.mock('../../components/datasets/catalog/DatasetDetailModal', () => ({
  DatasetDetailModal: () => null,
}));

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { apiFetch } = require('../../utils/authApi') as { apiFetch: jest.Mock };

const source: DiscoverySourceRow = {
  sourceId: 'source.curio.example-storage',
  dirName: 'source.curio.example-storage@1',
  name: 'Example storage',
  version: '1.0.0',
  description: '',
  publisher: 'Curio',
  homepage: null,
  license: '',
  tags: [],
  iconUrl: null,
  provider: 'folder',
  baseUrl: '',
  auth: { mode: 'public', required: false, usesToken: false, secretId: null, present: false, helpUrl: null },
  capabilities: { search: true, describe: true, download: true, formats: ['parquet'], maxDownloadBytes: 1 },
  kind: 'storage',
  resources: [],
  createdAt: null,
  updatedAt: null,
};

const row = {
  sourceId: source.sourceId,
  sourceName: source.name,
  resourceId: 'air-quality',
  name: 'Air quality readings',
  description: 'Table · 9 files',
  publisher: 'Curio',
  formats: ['parquet'],
  updatedAt: null,
  landingUrl: null,
  sizeHint: 900,
  acquirable: true,
  alreadyHeldDatasetId: null,
  kind: 'table',
  fileCount: 9,
  fieldValues: [],
  samples: [],
};

function listing(status: string, over: Record<string, unknown> = {}) {
  return {
    resources: status === 'ok' ? [row] : [],
    sources: [{ sourceId: source.sourceId, status, count: 0 }],
    nextCursor: null,
    totalHint: null,
    truncated: false,
    unmatched: 3,
    scannedAt: null,
    ...over,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/catalog/discovery/source.curio.example-storage@1']}>
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
  mockShowToast.mockReset();
  jest.useFakeTimers();
});

async function settlePage() {
  // The source loads first; the listing is asked once its debounce passes.
  await act(async () => {
    await jest.advanceTimersByTimeAsync(0);
  });
  await act(async () => {
    await jest.advanceTimersByTimeAsync(200);
  });
}
afterEach(() => jest.useRealTimers());
afterEach(resetDiscoveryAcquisitions);

test('a scan in progress is followed until its rows arrive', async () => {
  const answers = [listing('scanning'), listing('ok')];
  apiFetch.mockImplementation((path: string) => {
    if (path.includes('/search')) return Promise.resolve(answers.shift() ?? listing('ok'));
    return Promise.resolve(source);
  });
  renderPage();
  // The source loads first; the listing is asked once its debounce passes.
  await act(async () => {
    await jest.advanceTimersByTimeAsync(0);
  });
  await act(async () => {
    await jest.advanceTimersByTimeAsync(200);
  });
  expect(screen.getByText('Scanning Example storage…')).toBeInTheDocument();
  await act(async () => {
    await jest.advanceTimersByTimeAsync(1100);
  });
  expect(screen.getByText('Air quality readings')).toBeInTheDocument();
  expect(screen.getByText('3 files match no resource in this source\'s manifest.')).toBeInTheDocument();
  expect(screen.getByText('1 resource')).toBeInTheDocument();
});

test('Rescan asks for a new scan', async () => {
  apiFetch.mockImplementation((path: string) =>
    Promise.resolve(path.includes('/search') ? listing('ok', { unmatched: 0 }) : source),
  );
  renderPage();
  // The source loads first; the listing is asked once its debounce passes.
  await act(async () => {
    await jest.advanceTimersByTimeAsync(0);
  });
  await act(async () => {
    await jest.advanceTimersByTimeAsync(200);
  });
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Rescan' }));
    await jest.advanceTimersByTimeAsync(10);
  });
  await waitFor(() =>
    expect(apiFetch).toHaveBeenCalledWith(
      '/api/discovery/sources/source.curio.example-storage%401/search?rescan=1',
      expect.anything(),
    ),
  );
  expect(screen.queryByText(/match no resource/)).toBeNull();
});

test('a scan that failed says why, and not that the source is empty', async () => {
  const detail = 'Example storage: its folder is not available on this machine';
  apiFetch.mockImplementation((path: string) =>
    Promise.resolve(
      path.includes('/search')
        ? listing('failed', { sources: [{ sourceId: source.sourceId, status: 'failed', detail }], unmatched: 0 })
        : source,
    ),
  );
  renderPage();
  await settlePage();
  expect(screen.getByText(detail)).toBeInTheDocument();
  expect(screen.queryByText(/No files in Example storage match/)).toBeNull();
});

test('an add the server refuses is said on its row', async () => {
  apiFetch.mockImplementation((path: string) => {
    if (path.includes('/acquire')) {
      return Promise.reject(new Error('you already have 2 downloads running - wait for one to finish'));
    }
    return Promise.resolve(path.includes('/search') ? listing('ok', { unmatched: 0 }) : source);
  });
  renderPage();
  await settlePage();
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Add to Data Catalog' }));
    await jest.advanceTimersByTimeAsync(0);
  });
  expect(screen.getByRole('alert')).toHaveTextContent('you already have 2 downloads running');
});

test('adding a row again whose files did not change says so', async () => {
  const held = { ...row, alreadyHeldDatasetId: 'imported.xabc@1' };
  apiFetch.mockImplementation((path: string, opts?: RequestInit) => {
    if (path.includes('/acquire')) {
      expect(JSON.parse(String(opts?.body))).toEqual({ title: 'Air quality readings', refresh: true });
      return Promise.resolve({ jobId: 'j1', status: 'queued' });
    }
    if (path.startsWith('/api/discovery/jobs/')) {
      return Promise.resolve({
        jobId: 'j1', status: 'completed', alreadyPresent: true, unchanged: true,
        datasetId: 'imported.xabc@1', dataset: { title: 'Air quality readings' },
      });
    }
    return Promise.resolve(path.includes('/search') ? listing('ok', { unmatched: 0, resources: [held] }) : source);
  });
  renderPage();
  await settlePage();
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Add again' }));
    await jest.advanceTimersByTimeAsync(2000);
  });
  expect(mockShowToast).toHaveBeenCalledWith(
    'Nothing has changed in Air quality readings since it was added.',
    'info',
    expect.anything(),
  );
});
