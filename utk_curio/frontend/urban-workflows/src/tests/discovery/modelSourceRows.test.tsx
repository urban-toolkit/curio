import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { DiscoveryResourceRow } from '../../pages/discovery/DiscoveryResourceRow';
import {
  DISCOVERY_PROVIDER_LABEL,
  DISCOVERY_RESOURCE_KIND_LABEL,
  isModelSource,
  type DiscoveryAcquireJob,
  type DiscoveryResource,
} from '../../services/discoveryCatalog';
import { PROVIDER_FILTERS } from '../../pages/discovery/discoveryBrowseConstants';

function model(over: Partial<DiscoveryResource> = {}): DiscoveryResource {
  return {
    sourceId: 'source.huggingface.models',
    sourceName: 'Hugging Face models',
    resourceId: 'openmmlab/upernet-convnext-tiny',
    name: 'openmmlab/upernet-convnext-tiny',
    description: 'image-segmentation, safetensors weights, license mit',
    publisher: 'openmmlab',
    formats: ['model'],
    updatedAt: null,
    landingUrl: 'https://huggingface.co/openmmlab/upernet-convnext-tiny',
    sizeHint: null,
    acquirable: true,
    alreadyHeldDatasetId: null,
    alreadyHeldModelId: null,
    kind: 'model',
    ...over,
  };
}

function finished(over: Partial<DiscoveryAcquireJob> = {}): DiscoveryAcquireJob {
  return {
    jobId: 'j1', status: 'completed', bytesRead: 0, totalBytes: null, stageMessage: 'Added to your Model Catalog',
    error: null, datasetId: null, dataset: null, alreadyPresent: false, unchanged: false,
    sourceId: 'source.huggingface.models@1', resourceId: 'openmmlab/upernet-convnext-tiny',
    model: { id: 'imported.xabc123def456', name: 'openmmlab/upernet-convnext-tiny' },
    ...over,
  };
}

describe('a model source row', () => {
  test('is added to the Model Catalog, not downloaded', () => {
    const onDownload = jest.fn();
    render(<DiscoveryResourceRow resource={model()} onDownload={onDownload} />);
    expect(screen.queryByRole('button', { name: 'Download' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Add to Model Catalog' }));
    expect(onDownload).toHaveBeenCalledWith(expect.objectContaining({ resourceId: 'openmmlab/upernet-convnext-tiny' }), 'model');
  });

  test('says Model, not a file format, and links the model page', () => {
    render(<DiscoveryResourceRow resource={model()} />);
    expect(screen.getByText('Model')).toBeInTheDocument();
    expect(screen.queryByText('MODEL', { selector: 'span' })).toBeNull();
    expect(screen.getByRole('link', { name: /View the model's page/ })).toHaveAttribute(
      'href', 'https://huggingface.co/openmmlab/upernet-convnext-tiny',
    );
  });

  test('a held one says so and opens the model', () => {
    const onViewModel = jest.fn();
    render(
      <DiscoveryResourceRow
        resource={model({ alreadyHeldModelId: 'imported.xabc123def456' })}
        onViewModel={onViewModel}
        onViewDataset={jest.fn()}
      />,
    );
    expect(screen.getByText('In your Model Catalog')).toBeInTheDocument();
    expect(screen.queryByText(/In your Data Catalog/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'View dataset' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'View model' }));
    expect(onViewModel).toHaveBeenCalledWith('imported.xabc123def456');
  });

  test('a finished add opens the model it made', () => {
    const onViewModel = jest.fn();
    render(<DiscoveryResourceRow resource={model()} job={finished()} onViewModel={onViewModel} />);
    fireEvent.click(screen.getByRole('button', { name: 'View model' }));
    expect(onViewModel).toHaveBeenCalledWith('imported.xabc123def456');
  });
});

test('the model family has its kind, its provider label and its filter chip', () => {
  expect(isModelSource({ kind: 'model' })).toBe(true);
  expect(isModelSource({ kind: 'portal' })).toBe(false);
  expect(DISCOVERY_RESOURCE_KIND_LABEL.model).toBe('Model');
  expect(DISCOVERY_PROVIDER_LABEL['huggingface-models']).toBe('Hugging Face models');
  expect(PROVIDER_FILTERS.map((f) => f.value)).toContain('huggingface-models');
});
