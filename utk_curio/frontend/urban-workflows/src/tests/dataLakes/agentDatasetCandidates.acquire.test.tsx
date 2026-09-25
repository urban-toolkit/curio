import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';

import { AgentDatasetCandidatesCard, composeConfirmationPrompt } from '../../components/agents/content/AgentDatasetCandidatesCard';
import type { AgentDatasetCandidateRow } from '../../api/agentsApi';
import { dataLakeCatalogApi } from '../../services/dataLakeCatalog/dataLakeCatalogApi';
import { resetLakeAcquisitions } from '../../services/dataLakeCatalog/dataLakeCatalogHooks';

jest.mock('../../services/dataLakeCatalog/dataLakeCatalogApi', () => ({
  dataLakeCatalogApi: { acquire: jest.fn(), getJob: jest.fn(), cancelJob: jest.fn() },
}));
jest.mock('../../services/datasetCatalog/datasetCatalogApi', () => ({
  notifyDatasetCatalogRefresh: jest.fn(),
}));

/**
 * The external lane used to mean exactly one thing: hand it to Node Builder.
 * A row Curio can actually download now has its own Download, the same one the
 * Data Lake Catalog page runs - while a row it cannot still goes to Node
 * Builder, which is the right answer for a source no provider covers.
 */

const external = (over: Partial<AgentDatasetCandidateRow> = {}): AgentDatasetCandidateRow => ({
  name: 'Bike Routes',
  sourceType: 'lake',
  ...over,
});

const catalogRow = (over: Partial<AgentDatasetCandidateRow> = {}): AgentDatasetCandidateRow => ({
  name: 'Chicago Boundary',
  sourceType: 'catalog',
  datasetId: 'data.urbanlab.chicago-boundary',
  ...over,
});

describe('composeConfirmationPrompt', () => {
  test('a downloadable row is not asked for in the chat: its button downloads it', () => {
    const prompt = composeConfirmationPrompt(
      [],
      [external({ acquirable: true, sourceId: 'lake.a.b@1', resourceId: 'abcd-1234' })]
    );
    expect(prompt).toBe('');
    expect(
      composeConfirmationPrompt(
        [], [external({ acquirable: true, sourceId: 'lake.a.b@1', resourceId: 'r' })], 'builder',
      ),
    ).toBe('');
  });

  test('a row without a coordinate still goes to Node Builder', () => {
    const prompt = composeConfirmationPrompt([], [external({ url: 'https://a.example/x' })]);
    expect(prompt).toContain('hand off to Node Builder');
    expect(prompt).not.toContain('download into my Data Catalog');
  });

  test('a row the runtime did not mark acquirable goes to Node Builder', () => {
    // The model may name a source; only the runtime says it can be acted on.
    const prompt = composeConfirmationPrompt(
      [],
      [external({ sourceId: 'lake.made.up@1', resourceId: 'x' })]
    );
    expect(prompt).toContain('hand off to Node Builder');
  });

  test('a mixed selection asks for the rest, in one prompt', () => {
    const prompt = composeConfirmationPrompt(
      [catalogRow()],
      [
        external({ acquirable: true, sourceId: 'lake.a.b@1', resourceId: 'r1' }),
        external({ name: 'Something Else', url: 'https://a.example/y' }),
      ]
    );
    expect(prompt).toContain('install from the Data Catalog');
    expect(prompt).not.toContain('download');
    expect(prompt).toContain('hand off to Node Builder: Something Else');
  });

  test('nothing selected composes nothing', () => {
    expect(composeConfirmationPrompt([], [])).toBe('');
  });
});

describe('the Downloadable chip', () => {
  const renderCard = (rows: AgentDatasetCandidateRow[]) =>
    render(
      <AgentDatasetCandidatesCard
        part={{ type: 'datasetCandidates', lanes: { external: rows, catalog: [] } } as never}
      />
    );

  test('marks a row the runtime said can be downloaded', () => {
    renderCard([external({ acquirable: true, sourceId: 'lake.a.b@1', resourceId: 'r1' })]);
    expect(screen.getByText('Downloadable')).toBeInTheDocument();
  });

  test('is absent when the runtime did not say so', () => {
    renderCard([external({ url: 'https://a.example/x' })]);
    expect(screen.queryByText('Downloadable')).toBeNull();
  });
});

describe('the Download button', () => {
  const api = dataLakeCatalogApi as jest.Mocked<typeof dataLakeCatalogApi>;
  const row = external({ acquirable: true, sourceId: 'lake.a.b@1', resourceId: 'r1' });
  const part = { type: 'datasetCandidates', lanes: { external: [row], catalog: [] } } as never;
  const recorded = { attachmentId: 'att', status: 'resolved', picks: [] };

  beforeEach(() => {
    jest.useFakeTimers();
    resetLakeAcquisitions();
    api.acquire.mockReset();
    api.getJob.mockReset();
  });
  afterEach(() => jest.useRealTimers());

  const job = (over = {}) => ({
    jobId: 'j1', status: 'running', bytesRead: 0, totalBytes: null, stageMessage: '',
    error: null, datasetId: null, dataset: null, alreadyPresent: false, unchanged: false,
    sourceId: 'lake.a.b@1', resourceId: 'r1', ...over,
  });

  test('a resource already held is confirmed as the source at once', async () => {
    api.acquire.mockResolvedValue({ alreadyPresent: true, dataset: { id: 'imported.held' } } as never);
    const onRecordSelection = jest.fn().mockResolvedValue(recorded);
    render(<AgentDatasetCandidatesCard part={part} onRecordSelection={onRecordSelection} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    });
    expect(api.acquire).toHaveBeenCalledWith('lake.a.b@1', 'r1', {});
    expect(onRecordSelection).toHaveBeenCalledWith([{ lane: 'catalog', key: 'imported.held' }]);
    expect(screen.getByRole('button', { name: 'Downloaded' })).toBeDisabled();
  });

  test('a download is followed to the end, even after the card unmounts', async () => {
    api.acquire.mockResolvedValue(job() as never);
    api.getJob.mockResolvedValueOnce(job({ bytesRead: 5, totalBytes: 10 }) as never)
      .mockResolvedValueOnce(job({ status: 'completed', datasetId: 'imported.new' }) as never);
    const onRecordSelection = jest.fn().mockResolvedValue(recorded);
    const view = render(<AgentDatasetCandidatesCard part={part} onRecordSelection={onRecordSelection} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    });
    await act(async () => { jest.advanceTimersByTime(1000); });
    expect(screen.getByRole('button', { name: 'Downloading… 50%' })).toBeDisabled();
    view.unmount();
    await act(async () => { jest.advanceTimersByTime(5000); });
    expect(onRecordSelection).toHaveBeenCalledWith([{ lane: 'catalog', key: 'imported.new' }]);
    // Back on screen, the card shows how it ended.
    render(<AgentDatasetCandidatesCard part={part} onRecordSelection={onRecordSelection} />);
    expect(screen.getByRole('button', { name: 'Downloaded' })).toBeInTheDocument();
  });

  test('a refused download is a failure the card names, and records nothing', async () => {
    api.acquire.mockResolvedValue(job() as never);
    api.getJob.mockResolvedValue(job({ status: 'refused', error: 'that resource is an archive' }) as never);
    const onRecordSelection = jest.fn();
    render(<AgentDatasetCandidatesCard part={part} onRecordSelection={onRecordSelection} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    });
    await act(async () => { jest.advanceTimersByTime(1000); });
    expect(screen.getByRole('alert')).toHaveTextContent('that resource is an archive');
    expect(screen.getByRole('button', { name: 'Retry download' })).toBeEnabled();
    expect(onRecordSelection).not.toHaveBeenCalled();
  });

  test('with no node to confirm for, the download still lands and says so', async () => {
    api.acquire.mockResolvedValue({ alreadyPresent: true, dataset: { id: 'imported.held' } } as never);
    render(<AgentDatasetCandidatesCard part={part} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    });
    expect(screen.getByRole('status')).toHaveTextContent('Bike Routes is in your Data Catalog.');
  });
});
