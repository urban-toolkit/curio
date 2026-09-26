import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { DataLakeCatalogBrowse } from '../../pages/dataLakes/DataLakeCatalogBrowse';
import { DatasetDetailsProvider } from '../../components/datasets/catalog/DatasetDetailsProvider';
import { DataLakeSourceDetail } from '../../pages/dataLakes/DataLakeSourceDetail';
import { invalidateLakeCatalogCache } from '../../services/dataLakeCatalog';
import type { LakeSourceRow } from '../../services/dataLakeCatalog';

/**
 * "View dataset" on a lake row opens the Data Catalog's details modal.
 *
 * It was an `<a href="/catalog/data/:id">`, so the one place a downloaded
 * dataset is reached from its portal left the lake page for the full-page
 * detail route, while the Data, Node and Agent catalogs all open details in a
 * modal and stay where you are. The modal is stubbed: what is asserted is
 * which container the page opens and that the page does not move, and the
 * modal's own contents are covered in DatasetDetailPanel.test.tsx.
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

jest.mock('../../components/datasets/catalog/DatasetDetailModal', () => ({
  DatasetDetailModal: ({ datasetId, onClose }: { datasetId: string; onClose: () => void }) => (
    <div role="dialog" aria-label="Dataset details" data-dataset-id={datasetId}>
      <button type="button" onClick={onClose}>
        Close
      </button>
    </div>
  ),
}));

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { apiFetch } = require('../../utils/authApi') as { apiFetch: jest.Mock };

const source = (over: Partial<LakeSourceRow> = {}): LakeSourceRow => ({
  sourceId: 'lake.a.portal',
  dirName: 'lake.a.portal@1',
  name: 'Alpha Portal',
  version: '1.0.0',
  description: 'Alpha datasets.',
  publisher: 'Alpha City',
  homepage: null,
  license: '',
  tags: [],
  iconUrl: null,
  provider: 'socrata',
  baseUrl: 'https://alpha.example',
  auth: {
    mode: 'public', required: false, usesToken: false,
    secretId: null, present: false, helpUrl: null,
  },
  capabilities: {
    search: true, describe: true, download: true,
    formats: ['csv'], maxDownloadBytes: 67108864,
  },
  createdAt: null,
  updatedAt: null,
  ...over,
});

const heldRow = {
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
  alreadyHeldDatasetId: 'imported.xdeadbeef',
};

const searchResponse = {
  resources: [heldRow],
  sources: [{ sourceId: 'lake.a.portal', status: 'ok', count: 1 }],
  nextCursor: null,
  totalHint: 1,
  truncated: false,
};

/** Route the mocked client by path. The first match wins, so `/search` is
 *  listed before the source path that a single portal's search extends. */
function routeApi(handlers: [string, unknown][]) {
  apiFetch.mockImplementation((path: string) => {
    for (const [fragment, value] of handlers) {
      if (path.includes(fragment)) return Promise.resolve(value);
    }
    return Promise.reject(new Error(`unexpected call: ${path}`));
  });
}

let location = '';
const LocationProbe: React.FC = () => {
  const loc = useLocation();
  location = `${loc.pathname}${loc.search}`;
  return null;
};

function renderAt(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <DatasetDetailsProvider closeOnNavigate>
        <Routes>
          <Route path="/catalog/lakes" element={<DataLakeCatalogBrowse />} />
          <Route path="/catalog/lakes/:sourceDir" element={<DataLakeSourceDetail />} />
          <Route path="/catalog/data/:datasetId" element={<p>Dataset page</p>} />
        </Routes>
      </DatasetDetailsProvider>
      <LocationProbe />
    </MemoryRouter>
  );
}

beforeEach(() => {
  invalidateLakeCatalogCache();
  apiFetch.mockReset();
  location = '';
});

describe.each([
  ['the federated search', '/catalog/lakes?q=bike'],
  ['a single portal page', '/catalog/lakes/lake.a.portal@1?q=bike'],
])('View dataset on %s', (_where, entry) => {
  beforeEach(() => {
    routeApi([
      ['/api/datalakes/catalog', { sources: [source()], facets: { provider: { socrata: 1 }, auth: {} } }],
      ['/search', searchResponse],
      ['/api/datalakes/sources/', source()],
    ]);
  });

  test('opens the dataset details modal on the dataset it landed as', async () => {
    renderAt(entry);
    const row = (await screen.findByText('Bike Routes')).closest('[data-lake-resource]') as HTMLElement;
    fireEvent.click(within(row).getByRole('button', { name: 'View dataset' }));

    const dialog = screen.getByRole('dialog', { name: 'Dataset details' });
    expect(dialog).toHaveAttribute('data-dataset-id', 'imported.xdeadbeef');
  });

  test('stays on the lake page', async () => {
    renderAt(entry);
    const row = (await screen.findByText('Bike Routes')).closest('[data-lake-resource]') as HTMLElement;
    fireEvent.click(within(row).getByRole('button', { name: 'View dataset' }));

    expect(location).toBe(entry);
    expect(screen.queryByText('Dataset page')).toBeNull();
    // Still the lake page underneath, with the search that found the row.
    expect(screen.getByText('Bike Routes')).toBeInTheDocument();
  });

  test('closing the modal leaves the results where they were', async () => {
    renderAt(entry);
    const row = (await screen.findByText('Bike Routes')).closest('[data-lake-resource]') as HTMLElement;
    fireEvent.click(within(row).getByRole('button', { name: 'View dataset' }));
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));

    expect(screen.queryByRole('dialog', { name: 'Dataset details' })).toBeNull();
    expect(screen.getByText('Bike Routes')).toBeInTheDocument();
    expect(location).toBe(entry);
  });
});
