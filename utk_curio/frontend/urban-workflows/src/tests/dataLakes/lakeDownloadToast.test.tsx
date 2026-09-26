import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { DataLakeSourceDetail } from '../../pages/dataLakes/DataLakeSourceDetail';
import { invalidateLakeCatalogCache } from '../../services/dataLakeCatalog';

/**
 * A finished download says so, like an import does.
 *
 * Importing a file raised "Registered ... in the Data Catalog."; downloading
 * the same kind of file from a portal raised nothing, and the only sign it had
 * landed was the row's button changing. It now toasts, with the "View details"
 * every toast about a dataset carries.
 */

jest.mock('../../utils/authApi', () => ({
  apiFetch: jest.fn(),
  getToken: jest.fn(() => 'token'),
}));

const mockShowToast = jest.fn();
jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { apiFetch } = require('../../utils/authApi') as { apiFetch: jest.Mock };

const source = {
  sourceId: 'lake.a.portal',
  dirName: 'lake.a.portal@1',
  name: 'Alpha Portal',
  version: '1.0.0',
  description: '',
  publisher: 'Alpha City',
  homepage: null,
  license: '',
  tags: [],
  iconUrl: null,
  provider: 'socrata',
  baseUrl: 'https://alpha.example',
  auth: { mode: 'public', required: false, usesToken: false, secretId: null, present: false, helpUrl: null },
  capabilities: { search: true, describe: true, download: true, formats: ['csv'], maxDownloadBytes: 67108864 },
  createdAt: null,
  updatedAt: null,
};

const row = {
  sourceId: 'lake.a.portal',
  sourceName: 'Alpha Portal',
  resourceId: 'abcd-1234',
  name: 'Bike Routes',
  description: '',
  publisher: 'Alpha City',
  formats: ['csv'],
  updatedAt: null,
  landingUrl: null,
  sizeHint: null,
  acquirable: true,
  alreadyHeldDatasetId: null,
};

const job = (over: Record<string, unknown>) => ({
  jobId: 'j1',
  status: 'running',
  bytesRead: 0,
  totalBytes: null,
  stageMessage: 'Downloading…',
  error: null,
  datasetId: null,
  dataset: null,
  alreadyPresent: false,
  unchanged: false,
  sourceId: 'lake.a.portal@1',
  resourceId: 'abcd-1234',
  ...over,
});

beforeEach(() => {
  invalidateLakeCatalogCache();
  mockShowToast.mockReset();
  apiFetch.mockReset();
  apiFetch.mockImplementation((path: string) => {
    if (path.includes('/search')) {
      return Promise.resolve({ resources: [row], sources: [], nextCursor: null, totalHint: 1, truncated: false });
    }
    if (path.includes('/acquire')) return Promise.resolve(job({ status: 'queued' }));
    if (path.includes('/api/datalakes/jobs/')) {
      return Promise.resolve(
        job({ status: 'completed', datasetId: 'imported.xbikes', dataset: { title: 'Bike Routes' } })
      );
    }
    if (path.includes('/api/datalakes/sources/')) return Promise.resolve(source);
    return Promise.reject(new Error(`unexpected call: ${path}`));
  });
});

test('a finished download toasts, with a way to the dataset', async () => {
  render(
    <MemoryRouter initialEntries={['/catalog/lakes/lake.a.portal@1?q=bike']}>
      <Routes>
        <Route path="/catalog/lakes/:sourceDir" element={<DataLakeSourceDetail />} />
      </Routes>
    </MemoryRouter>
  );
  const title = await screen.findByText('Bike Routes');
  const card = title.closest('[data-lake-resource]') as HTMLElement;
  fireEvent.click(within(card).getByRole('button', { name: 'Download' }));

  await waitFor(
    () =>
      expect(mockShowToast).toHaveBeenCalledWith(
        'Downloaded Bike Routes to your Data Catalog.',
        'success',
        { action: expect.objectContaining({ label: 'View details' }) }
      ),
    { timeout: 4000 }
  );
});
