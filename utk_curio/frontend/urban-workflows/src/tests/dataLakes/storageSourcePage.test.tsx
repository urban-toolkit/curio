/**
 * A storage source's page: its declared resources as its last scan found
 * them, a scan followed until it ends, the files no resource declares, and
 * Rescan.
 */
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { DataLakeSourceDetail } from '../../pages/dataLakes/DataLakeSourceDetail';
import { DatasetDetailsProvider } from '../../components/datasets/catalog/DatasetDetailsProvider';
import type { LakeSourceRow } from '../../services/dataLakeCatalog';

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

const source: LakeSourceRow = {
  sourceId: 'lake.curio.example-storage',
  dirName: 'lake.curio.example-storage@1',
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
    <MemoryRouter initialEntries={['/catalog/lakes/lake.curio.example-storage@1']}>
      <DatasetDetailsProvider closeOnNavigate>
        <Routes>
          <Route path="/catalog/lakes/:sourceDir" element={<DataLakeSourceDetail />} />
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
      '/api/datalakes/sources/lake.curio.example-storage%401/search?rescan=1',
      expect.anything(),
    ),
  );
  expect(screen.queryByText(/match no resource/)).toBeNull();
});
