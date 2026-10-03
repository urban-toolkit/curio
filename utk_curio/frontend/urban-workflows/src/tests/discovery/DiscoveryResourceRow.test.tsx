import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';

import { DiscoveryResourceRow } from '../../pages/discovery/DiscoveryResourceRow';
import type { DiscoveryAcquireJob, DiscoveryResource } from '../../services/discoveryCatalog';

function resource(over: Partial<DiscoveryResource> = {}): DiscoveryResource {
  return {
    sourceId: 'source.a.portal',
    sourceName: 'Alpha Portal',
    resourceId: 'abcd-1234',
    name: 'Bike Routes',
    description: 'Every cycle route in the city.',
    publisher: 'Alpha City',
    formats: ['geojson'],
    updatedAt: '2026-01-15T00:00:00Z',
    landingUrl: 'https://alpha.example/d/abcd-1234',
    sizeHint: null,
    acquirable: true,
    alreadyHeldDatasetId: null,
    ...over,
  };
}

describe('DiscoveryResourceRow', () => {
  test('shows the name, publisher and when it changed', () => {
    render(<DiscoveryResourceRow resource={resource()} />);
    expect(screen.getByText('Bike Routes')).toBeInTheDocument();
    expect(screen.getByText(/Alpha City/)).toBeInTheDocument();
    expect(screen.getByText(/2026-01-15/)).toBeInTheDocument();
  });

  test('renders each format as the shared badge', () => {
    // Same component the Data Catalog uses, so a CSV is the same colour in
    // both places. Scoped to the badge: the format picker's <option> carries
    // the same text, and matching either would not prove the badge rendered.
    render(<DiscoveryResourceRow resource={resource({ formats: ['csv', 'geojson'] })} />);
    expect(screen.getByText('CSV', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByText('GEOJSON', { selector: 'span' })).toBeInTheDocument();
  });

  test('offers a format picker only when there is a choice', () => {
    const { rerender } = render(<DiscoveryResourceRow resource={resource()} />);
    expect(screen.queryByRole('combobox')).toBeNull();
    rerender(<DiscoveryResourceRow resource={resource({ formats: ['csv', 'geojson'] })} />);
    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });

  test('hands the chosen format to the download handler', () => {
    const onDownload = jest.fn();
    render(
      <DiscoveryResourceRow
        resource={resource({ formats: ['csv', 'geojson'] })}
        onDownload={onDownload}
      />
    );
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'geojson' } });
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    expect(onDownload).toHaveBeenCalledWith(expect.objectContaining({ name: 'Bike Routes' }), 'geojson');
  });

  test('the download button is disabled where there is no handler', () => {
    // A button that looks live and does nothing is worse than one that says so.
    render(<DiscoveryResourceRow resource={resource()} />);
    expect(screen.getByRole('button', { name: 'Download' })).toBeDisabled();
  });

  test('it is enabled once a handler is given', () => {
    render(<DiscoveryResourceRow resource={resource()} onDownload={jest.fn()} />);
    expect(screen.getByRole('button', { name: 'Download' })).toBeEnabled();
  });

  test('a row already held says so, and offers it instead of a second copy', () => {
    const onViewDataset = jest.fn();
    render(
      <DiscoveryResourceRow
        resource={resource({ alreadyHeldDatasetId: 'imported.xdeadbeef', heldFormats: { geojson: 'imported.xdeadbeef' } })}
        onDownload={jest.fn()}
        onViewDataset={onViewDataset}
      />
    );
    expect(screen.getByText('In your Data Catalog as GEOJSON')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'View dataset' }));
    expect(onViewDataset).toHaveBeenCalledWith('imported.xdeadbeef');
    expect(screen.queryByRole('button', { name: 'Download' })).toBeNull();
  });

  test('View dataset is a button, not a link to the dataset page', () => {
    // It was an <a href="/catalog/data/:id">, so it left the Discovery Catalog page for the
    // Data Catalog's full-page view, while every other way into a dataset's
    // details opens the modal and stays put.
    render(
      <DiscoveryResourceRow
        resource={resource({ alreadyHeldDatasetId: 'imported.xdeadbeef', heldFormats: { geojson: 'imported.xdeadbeef' } })}
        onViewDataset={jest.fn()}
      />
    );
    expect(screen.queryByRole('link', { name: 'View dataset' })).toBeNull();
    expect(screen.getByRole('button', { name: 'View dataset' })).toBeInTheDocument();
  });

  test('a non-acquirable row cannot be downloaded even with a handler', () => {
    render(
      <DiscoveryResourceRow resource={resource({ acquirable: false })} onDownload={jest.fn()} />
    );
    expect(screen.getByRole('button', { name: 'Download' })).toBeDisabled();
  });

  test('a row that cannot be downloaded says why, on the button and in the row', () => {
    const reason = 'Bike Routes is larger than this portal allows';
    render(
      <DiscoveryResourceRow
        resource={resource({ acquirable: false, unavailableReason: reason })}
        onDownload={jest.fn()}
      />
    );
    const button = screen.getByRole('button', { name: 'Download' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('title', reason);
    expect(screen.getByRole('note')).toHaveTextContent(reason);
  });

  test('the source tag appears only on a federated result', () => {
    // On a single-portal page it would repeat the page heading on every row.
    const { rerender, container } = render(<DiscoveryResourceRow resource={resource()} />);
    expect(screen.queryByText('Alpha Portal')).toBeNull();
    rerender(<DiscoveryResourceRow resource={resource()} showSource />);
    expect(within(container).getByText('Alpha Portal')).toBeInTheDocument();
  });

  test('links out to the portal in a new tab, safely', () => {
    render(<DiscoveryResourceRow resource={resource()} />);
    const link = screen.getByRole('link', { name: /View on the portal/ });
    expect(link).toHaveAttribute('href', 'https://alpha.example/d/abcd-1234');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });
});


describe('DiscoveryResourceRow: a download in flight', () => {
  const job = (over: Partial<DiscoveryAcquireJob> = {}): DiscoveryAcquireJob => ({
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
    sourceId: 'source.a.portal@1',
    resourceId: 'abcd-1234',
    ...over,
  });

  test('shows a determinate bar when the portal declared a length', () => {
    render(
      <DiscoveryResourceRow
        resource={resource()}
        job={job({ bytesRead: 512, totalBytes: 2048 })}
      />
    );
    const bar = screen.getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '25');
    expect(screen.getByText('512 B')).toBeInTheDocument();
  });

  test('shows an indeterminate bar when it did not', () => {
    // Plenty of portals stream without a Content-Length, and a bar stuck at
    // 0% reads as broken.
    render(<DiscoveryResourceRow resource={resource()} job={job()} />);
    const bar = screen.getByRole('progressbar');
    expect(bar).not.toHaveAttribute('aria-valuenow');
    expect(screen.getByText('Downloading…')).toBeInTheDocument();
  });

  test('the download button gives way to Cancel', () => {
    const onCancel = jest.fn();
    render(
      <DiscoveryResourceRow resource={resource()} job={job()} onCancel={onCancel} onDownload={jest.fn()} />
    );
    expect(screen.queryByRole('button', { name: 'Download' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
  });

  test('a finished download opens where it landed', () => {
    const onViewDataset = jest.fn();
    render(
      <DiscoveryResourceRow
        resource={resource()}
        job={job({ status: 'completed', datasetId: 'imported.xabc' })}
        onViewDataset={onViewDataset}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: 'View dataset' }));
    expect(onViewDataset).toHaveBeenCalledWith('imported.xabc');
  });

  test.each(['failed', 'refused'] as const)(
    'a %s download shows the server own words, not a generic failure',
    (status) => {
      // The server knows whether the file was too large, an archive, or a
      // portal that refused. Any of those is more use than "download failed".
      render(
        <DiscoveryResourceRow
          resource={resource()}
          job={job({ status, error: 'that resource is a application/zip archive.' })}
        />
      );
      expect(screen.getByRole('alert')).toHaveTextContent('archive');
    }
  );

  test('a failure can be dismissed', () => {
    const onDismiss = jest.fn();
    render(
      <DiscoveryResourceRow
        resource={resource()}
        job={job({ status: 'failed', error: 'nope' })}
        onDismiss={onDismiss}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(onDismiss).toHaveBeenCalled();
  });

  test('a cancelled download offers the button again', () => {
    render(
      <DiscoveryResourceRow
        resource={resource()}
        job={job({ status: 'cancelled' })}
        onDownload={jest.fn()}
      />
    );
    expect(screen.getByRole('button', { name: 'Download' })).toBeInTheDocument();
  });
});

describe('a row held in one format (#477)', () => {
  const twoFormats = (over: Partial<DiscoveryResource> = {}) =>
    resource({
      formats: ['csv', 'geojson'],
      alreadyHeldDatasetId: 'imported.xcsv',
      heldFormats: { csv: 'imported.xcsv' },
      ...over,
    });

  test('offers the held format as a dataset and the other as a download', () => {
    const onDownload = jest.fn();
    render(<DiscoveryResourceRow resource={twoFormats()} onDownload={onDownload} onViewDataset={jest.fn()} />);
    expect(screen.getByText('In your Data Catalog as CSV')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'View dataset' })).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'geojson' } });
    expect(screen.queryByRole('button', { name: 'View dataset' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    expect(onDownload).toHaveBeenCalledWith(expect.objectContaining({ resourceId: 'abcd-1234' }), 'geojson');
  });

  test('a finished CSV download does not stand for the GeoJSON', () => {
    const job = {
      jobId: 'j1', status: 'completed', bytesRead: 10, totalBytes: 10, stageMessage: '', error: null,
      datasetId: 'imported.xcsv', dataset: { id: 'imported.xcsv', format: 'csv' },
      alreadyPresent: false, unchanged: false, sourceId: 'source.a.portal@1', resourceId: 'abcd-1234',
    } as DiscoveryAcquireJob;
    render(
      <DiscoveryResourceRow
        resource={twoFormats({ alreadyHeldDatasetId: null, heldFormats: {} })}
        job={job}
        onDownload={jest.fn()}
        onViewDataset={jest.fn()}
      />
    );
    expect(screen.getByRole('button', { name: 'View dataset' })).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'geojson' } });
    expect(screen.getByRole('button', { name: 'Download' })).toBeInTheDocument();
  });
});
