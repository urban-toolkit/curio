/**
 * A storage source's rows: added rather than downloaded, narrowed in the Add
 * dialog, and opened file by file.
 */
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import { DataLakeResourceRow } from '../../pages/dataLakes/DataLakeResourceRow';
import { filtersOf, narrowableFields, rangeProblem } from '../../pages/dataLakes/DataLakeAddDialog';
import type { LakeAcquireJob, LakeResourceRow } from '../../services/dataLakeCatalog';

jest.mock('../../utils/authApi', () => ({
  apiFetch: jest.fn(),
  getToken: () => 'tok',
}));
jest.mock('../../utils/backendUrl', () => ({ backendUrl: () => 'http://backend.test' }));

const { apiFetch } = require('../../utils/authApi') as { apiFetch: jest.Mock };

function row(over: Partial<LakeResourceRow> = {}): LakeResourceRow {
  return {
    sourceId: 'lake.curio.example-storage',
    sourceName: 'Example storage',
    resourceId: 'orthos',
    name: 'Drone orthoimagery',
    description: 'Rasters · 4 files · year 2023, 2024 · 20.0 KB',
    publisher: 'Curio',
    formats: ['collection'],
    updatedAt: null,
    landingUrl: null,
    sizeHint: 20480,
    acquirable: true,
    alreadyHeldDatasetId: null,
    kind: 'rasters',
    fileCount: 4,
    fieldValues: [
      { name: 'year', type: 'int', distinct: 2, values: ['2023', '2024'] },
      { name: 'tile', type: 'str', distinct: 2, values: ['tile_0001', 'tile_0002'] },
    ],
    samples: ['orthos/2023/tile_0001.tif', 'orthos/2023/tile_0002.tif'],
    ...over,
  };
}

beforeEach(() => {
  apiFetch.mockReset();
  (global as any).fetch = jest.fn().mockResolvedValue({ ok: false, status: 404 });
});

describe('a storage row', () => {
  test('shows its kind and its sample thumbnails, and is added rather than downloaded', () => {
    render(<DataLakeResourceRow resource={row()} storage={{ dirName: 'lake.x@1', onAdd: jest.fn() }} />);
    expect(screen.getByText('Rasters')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add to Data Catalog' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Download' })).toBeNull();
    expect((global as any).fetch).toHaveBeenCalledWith(
      'http://backend.test/api/datalakes/sources/lake.x%401/thumbnails/0/orthos',
      expect.anything(),
    );
  });

  test('a row with fields opens the Add dialog, which narrows by the kept values', () => {
    const onAdd = jest.fn();
    render(<DataLakeResourceRow resource={row()} storage={{ dirName: 'lake.x@1', onAdd }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Add to Data Catalog' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.click(within(dialog).getByLabelText('2023'));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add to Data Catalog' }));
    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({ resourceId: 'orthos' }),
      { title: 'Drone orthoimagery', filters: { year: ['2024'] } },
    );
  });

  test('a row with nothing to narrow is added straight away', () => {
    const onAdd = jest.fn();
    render(
      <DataLakeResourceRow
        resource={row({ fieldValues: [{ name: 'year', type: 'int', distinct: 1, values: ['2024'] }] })}
        storage={{ dirName: 'lake.x@1', onAdd }}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Add to Data Catalog' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(onAdd).toHaveBeenCalledWith(expect.anything(), { title: 'Drone orthoimagery' });
  });

  test('Files lists the row a page at a time and adds the picked files', async () => {
    apiFetch.mockResolvedValue({
      files: [
        { index: 0, relpath: 'orthos/2023/tile_0001.tif', size: 5120, updatedAt: null, values: { year: '2023', tile: 'tile_0001' } },
        { index: 1, relpath: 'orthos/2023/tile_0002.tif', size: 5120, updatedAt: null, values: { year: '2023', tile: 'tile_0002' } },
      ],
      total: 4,
      offset: 0,
      previews: true,
    });
    const onAdd = jest.fn();
    render(<DataLakeResourceRow resource={row()} storage={{ dirName: 'lake.x@1', onAdd }} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Files' }));
    });
    expect(apiFetch).toHaveBeenCalledWith(
      '/api/datalakes/sources/lake.x%401/files/orthos?limit=50',
      expect.anything(),
    );
    await waitFor(() => expect(screen.getByText('1 to 2 of 4')).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText('Pick orthos/2023/tile_0002.tif'));
    fireEvent.click(screen.getByRole('button', { name: 'Add 1 picked file' }));
    expect(onAdd).toHaveBeenCalledWith(expect.anything(), {
      title: 'Drone orthoimagery (1 file)',
      files: ['orthos/2023/tile_0002.tif'],
    });
  });

  test('a row already in the Data Catalog can be added again, as its files are now', () => {
    const onAdd = jest.fn();
    render(
      <DataLakeResourceRow
        resource={row({ alreadyHeldDatasetId: 'imported.xabc@1' })}
        storage={{ dirName: 'lake.x@1', onAdd }}
        onViewDataset={jest.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'View dataset' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Add again' }));
    expect(onAdd).toHaveBeenCalledWith(expect.anything(), { title: 'Drone orthoimagery', refresh: true });
  });

  test('adding part of a row leaves the whole row to add', () => {
    render(
      <DataLakeResourceRow
        resource={row()}
        storage={{ dirName: 'lake.x@1', onAdd: jest.fn() }}
        onViewDataset={jest.fn()}
        job={job({ status: 'completed', datasetId: 'imported.xpart@1', dataset: { lakeSource: { narrowed: true } } })}
      />,
    );
    expect(screen.getByRole('button', { name: 'Add to Data Catalog' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'View dataset' })).toBeNull();
  });

  test('a job on the row closes its Files list, whose Add would start a second one', async () => {
    apiFetch.mockResolvedValue({ files: [], total: 0, offset: 0, previews: false });
    const storage = { dirName: 'lake.x@1', onAdd: jest.fn() };
    const { rerender } = render(<DataLakeResourceRow resource={row()} storage={storage} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Files' }));
    });
    await waitFor(() => expect(screen.getByText('No files.')).toBeInTheDocument());
    rerender(<DataLakeResourceRow resource={row()} storage={storage} job={job({ status: 'running' })} />);
    expect(screen.queryByText('No files.')).toBeNull();
    rerender(<DataLakeResourceRow resource={row()} storage={storage} job={job({ status: 'failed', error: 'x' })} />);
    expect(screen.getByRole('button', { name: 'Files' })).toHaveAttribute('aria-expanded', 'false');
  });

  test('a per-file row has no Files list', () => {
    render(
      <DataLakeResourceRow
        resource={row({ kind: 'table', formats: ['csv'], resourceId: 'files/a.csv' })}
        storage={{
          dirName: 'lake.x@1',
          onAdd: jest.fn(),
          declared: {
            resourceId: 'files', name: 'Files', description: '', kind: 'table', format: 'csv',
            fileFormat: 'csv', path: '{name}.csv', datasets: 'per-file', splitBy: [], fields: [],
          },
        }}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Files' })).toBeNull();
  });
});

function job(over: Partial<LakeAcquireJob> = {}): LakeAcquireJob {
  return {
    jobId: 'j1',
    status: 'running',
    bytesRead: 0,
    totalBytes: null,
    stageMessage: 'Indexing…',
    error: null,
    datasetId: null,
    dataset: null,
    alreadyPresent: false,
    unchanged: false,
    sourceId: 'lake.x@1',
    resourceId: 'orthos',
    ...over,
  };
}

describe('narrowing', () => {
  const fields = row().fieldValues!;

  test('a split field is not narrowable, nor one with a single value', () => {
    expect(narrowableFields(row(), ['year']).map((f) => f.name)).toEqual(['tile']);
    expect(
      narrowableFields(row({ fieldValues: [{ name: 'x', type: 'str', distinct: 1, values: ['a'] }] }), []),
    ).toEqual([]);
  });

  test('a field kept whole adds no filter', () => {
    expect(
      filtersOf(fields, {
        year: { kind: 'values', kept: new Set(['2023', '2024']) },
        tile: { kind: 'values', kept: new Set(['tile_0001', 'tile_0002']) },
      }),
    ).toEqual({});
  });

  test('a moved bound becomes a range', () => {
    const ranged = [{ name: 'day', type: 'date', distinct: 400, min: '2024-01-01', max: '2025-02-04' }];
    expect(filtersOf(ranged, { day: { kind: 'range', min: '2024-06-01', max: '2025-02-04' } })).toEqual({
      day: { min: '2024-06-01', max: '2025-02-04' },
    });
  });
});

describe('a range to narrow by', () => {
  const year = { name: 'year', type: 'int', distinct: 30, min: '1990', max: '2024' };
  const day = { name: 'day', type: 'date', distinct: 400, min: '2024-01-01', max: '2025-02-04' };

  test('holds values, in order', () => {
    expect(rangeProblem(year, '2000', '2010')).toBeNull();
    expect(rangeProblem(day, '2024-06-01', '2024-06-30')).toBeNull();
  });

  test('is refused with a reason when it cannot hold a value', () => {
    expect(rangeProblem(year, '2010', '2000')).toBe('year starts after it ends.');
    expect(rangeProblem(year, '20x0', '2010')).toBe('year takes whole numbers.');
    expect(rangeProblem(day, '2024-06-01', '')).toBe('day needs both ends of its range.');
    expect(rangeProblem(day, '06/01/2024', '2024-06-30')).toBe('day takes dates like 2024-05-01.');
  });

  test('a backwards range keeps the dialog open and says why', () => {
    const onAdd = jest.fn();
    render(
      <DataLakeResourceRow
        resource={row({ fieldValues: [{ ...year }] })}
        storage={{ dirName: 'lake.x@1', onAdd }}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Add to Data Catalog' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('year from'), { target: { value: '2020' } });
    fireEvent.change(within(dialog).getByLabelText('year to'), { target: { value: '2001' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add to Data Catalog' }));
    expect(onAdd).not.toHaveBeenCalled();
    expect(within(dialog).getByText('year starts after it ends.')).toBeInTheDocument();
  });
});
