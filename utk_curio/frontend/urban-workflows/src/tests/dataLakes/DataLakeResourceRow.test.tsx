import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';

import { DataLakeResourceRow } from '../../pages/dataLakes/DataLakeResourceRow';
import type { LakeResourceRow } from '../../services/dataLakeCatalog';

function resource(over: Partial<LakeResourceRow> = {}): LakeResourceRow {
  return {
    sourceId: 'lake.a.portal',
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

describe('DataLakeResourceRow', () => {
  test('shows the name, publisher and when it changed', () => {
    render(<DataLakeResourceRow resource={resource()} />);
    expect(screen.getByText('Bike Routes')).toBeInTheDocument();
    expect(screen.getByText(/Alpha City/)).toBeInTheDocument();
    expect(screen.getByText(/2026-01-15/)).toBeInTheDocument();
  });

  test('renders each format as the shared badge', () => {
    // Same component the Data Catalog uses, so a CSV is the same colour in
    // both places. Scoped to the badge: the format picker's <option> carries
    // the same text, and matching either would not prove the badge rendered.
    render(<DataLakeResourceRow resource={resource({ formats: ['csv', 'geojson'] })} />);
    expect(screen.getByText('CSV', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByText('GEOJSON', { selector: 'span' })).toBeInTheDocument();
  });

  test('offers a format picker only when there is a choice', () => {
    const { rerender } = render(<DataLakeResourceRow resource={resource()} />);
    expect(screen.queryByRole('combobox')).toBeNull();
    rerender(<DataLakeResourceRow resource={resource({ formats: ['csv', 'geojson'] })} />);
    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });

  test('hands the chosen format to the download handler', () => {
    const onDownload = jest.fn();
    render(
      <DataLakeResourceRow
        resource={resource({ formats: ['csv', 'geojson'] })}
        onDownload={onDownload}
      />
    );
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'geojson' } });
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    expect(onDownload).toHaveBeenCalledWith(expect.objectContaining({ name: 'Bike Routes' }), 'geojson');
  });

  test('the download button is disabled while acquisition is unwired', () => {
    // A button that looks live and does nothing is worse than one that says so.
    render(<DataLakeResourceRow resource={resource()} />);
    const button = screen.getByRole('button', { name: 'Download' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('title', expect.stringContaining('not wired up'));
  });

  test('a row already held says so', () => {
    render(
      <DataLakeResourceRow
        resource={resource({ alreadyHeldDatasetId: 'imported.xdeadbeef' })}
        onDownload={jest.fn()}
      />
    );
    expect(screen.getByText('In your Data Catalog')).toBeInTheDocument();
  });

  test('a non-acquirable row cannot be downloaded even with a handler', () => {
    render(
      <DataLakeResourceRow resource={resource({ acquirable: false })} onDownload={jest.fn()} />
    );
    expect(screen.getByRole('button', { name: 'Download' })).toBeDisabled();
  });

  test('the source tag appears only on a federated result', () => {
    // On a single-portal page it would repeat the page heading on every row.
    const { rerender, container } = render(<DataLakeResourceRow resource={resource()} />);
    expect(screen.queryByText('Alpha Portal')).toBeNull();
    rerender(<DataLakeResourceRow resource={resource()} showSource />);
    expect(within(container).getByText('Alpha Portal')).toBeInTheDocument();
  });

  test('links out to the portal in a new tab, safely', () => {
    render(<DataLakeResourceRow resource={resource()} />);
    const link = screen.getByRole('link', { name: /View on the portal/ });
    expect(link).toHaveAttribute('href', 'https://alpha.example/d/abcd-1234');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });
});
