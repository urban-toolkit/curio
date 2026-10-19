import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { canvas, draw } from '../../_support/sidewalkEditorHarness';

const { useSidewalkTileEditBehavior } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/sidewalkTileEditBehavior');

const tile = (id: string, west: number, imageAvailable = true) => ({
  type: 'Feature', properties: { tile_id: id, x: west, y: 0, zoom: 19,
    image_url: `image-${id}.jpg`, image_available: imageAvailable, network_url: `network-${id}.geojson` },
  geometry: { type: 'Polygon', coordinates: [[[west, 0], [west + 1, 0], [west + 1, 1], [west, 1], [west, 0]]] },
});
const grid = { type: 'FeatureCollection', features: [tile('A', 0), tile('B', 1), tile('C', 2, false)] };
const mapPick = (index: number) => [{ details: { autk_selection: { data: [index], priority: 1,
  selectionOrigin: { version: 1, kind: 'map-pick', activeIndex: index } } } }];
const brush = (indices: number[]) => [{ details: { autk_selection: { data: indices, priority: 1,
  selectionOrigin: { version: 1, kind: 'plot-brush', candidateIndices: indices } } } }];

function Host({ interactions, sent, persisted, input = grid }: { interactions: unknown; sent: jest.Mock; persisted: jest.Mock; input?: typeof grid }) {
  const [code, setCode] = React.useState('');
  const result = useSidewalkTileEditBehavior({ nodeId: 'editor', input, interactions,
    outputCallback: jest.fn(), interactionsCallback: sent }, {
    code, setCode: (next: string) => { persisted(next); setCode(next); }, setOutput: jest.fn(),
  });
  return result.contentComponent;
}

function expectTileSummary(id: string, lines: number, drafts: number) {
  expect(screen.getByText(`Tile ${id}`)).toBeInTheDocument();
  expect(screen.getByText(`${lines} lines`)).toBeInTheDocument();
  expect(screen.getByText(drafts ? `${drafts} draft changes` : 'No draft changes')).toBeInTheDocument();
}

test('all four image navigation buttons use the same centered chevron', async () => {
  const previousFetch = global.fetch;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [] }) })) as unknown as typeof fetch;
  try {
    const view = render(<Host interactions={mapPick(1)} sent={jest.fn()} persisted={jest.fn()} />);
    await screen.findByAltText('Satellite image for tile B');
    fireEvent.load(screen.getByAltText('Satellite image for tile B'));
    const rotations: Record<string, string> = { north: '180deg', south: '0deg', east: '-90deg', west: '90deg' };
    const paths = Object.keys(rotations).map(direction => {
      const button = screen.getByRole('button', { name: `Navigate ${direction}` });
      expect(button).toHaveStyle({ width: '32px', height: '32px', display: 'grid', placeItems: 'center' });
      const svg = button.querySelector(`svg[data-tile-chevron="${direction}"]`);
      expect(svg).toHaveAttribute('viewBox', '0 0 24 24');
      expect(svg).toHaveAttribute('width', '20');
      expect(svg).toHaveAttribute('height', '20');
      expect(svg).toHaveStyle({ transform: `rotate(${rotations[direction]})` });
      return svg?.querySelector('path')?.getAttribute('d');
    });
    expect(new Set(paths).size).toBe(1);
    view.unmount();
  } finally { global.fetch = previousFetch; }
});

test('arrows preserve an unsaved draft and history through A → B → A without changing PCP candidates', async () => {
  const previousFetch = global.fetch;
  global.fetch = jest.fn(async (url: string) => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [
    { type: 'Feature', id: url, properties: {}, geometry: { type: 'LineString', coordinates: [
      [url.includes('network-B') ? 1.1 : 0.1, 0.1], [url.includes('network-B') ? 1.9 : 0.9, 0.9],
    ] } },
  ] }) })) as unknown as typeof fetch;
  const sent = jest.fn(); const persisted = jest.fn();
  try {
    const picked = mapPick(0);
    const view = render(<Host interactions={picked} sent={sent} persisted={persisted} />);
    await screen.findByAltText('Satellite image for tile A');
    fireEvent.load(screen.getByAltText('Satellite image for tile A'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save network' })).toBeEnabled());
    await draw(canvas(view.container));
    expectTileSummary('A', 2, 1);
    expect(screen.getByRole('button', { name: 'Undo' })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: 'Navigate east' }));
    expect(screen.getByText(/Loading tile B/)).toBeInTheDocument();
    await screen.findByAltText('Satellite image for tile B');
    fireEvent.load(screen.getByAltText('Satellite image for tile B'));
    await waitFor(() => expectTileSummary('B', 1, 0));
    expect(sent.mock.calls.some(([event]) => event.autk_selection?.data?.[0]?.tile_id === 'B')).toBe(true);
    expect(sent.mock.calls.some(([event]) => event['sidewalk.network-edit'])).toBe(false);

    view.rerender(<Host interactions={brush([0, 2])} sent={sent} persisted={persisted} />);
    expectTileSummary('B', 1, 0);
    fireEvent.click(screen.getByRole('button', { name: 'Navigate west' }));
    await screen.findByAltText('Satellite image for tile A');
    fireEvent.load(screen.getByAltText('Satellite image for tile A'));
    await waitFor(() => expectTileSummary('A', 2, 1));
    expect(screen.getByRole('button', { name: 'Undo' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Navigate west' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Navigate west' })).toHaveAttribute('title', 'No adjacent tile to the west');
    expect(persisted).toHaveBeenCalled();
  } finally { global.fetch = previousFetch; }
});

test('reused tile IDs in a different dataset do not reuse the previous active tile', async () => {
  const previousFetch = global.fetch;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [] }) })) as unknown as typeof fetch;
  try {
    const sent = jest.fn(); const persisted = jest.fn(); const picked = mapPick(0);
    const view = render(<Host interactions={picked} sent={sent} persisted={persisted} />);
    await screen.findByAltText('Satellite image for tile A');
    fireEvent.load(screen.getByAltText('Satellite image for tile A'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save network' })).toBeEnabled());
    const otherDataset = { type: 'FeatureCollection', features: [tile('A', 10), tile('B', 11)] };
    view.rerender(<Host interactions={picked} sent={sent} persisted={persisted} input={otherDataset} />);
    await waitFor(() => expect(screen.getAllByText(/Waiting for tile selection/).length).toBeGreaterThan(0));
    expect(screen.getByRole('button', { name: 'Save network' })).toBeDisabled();
    const newPick = mapPick(0);
    view.rerender(<Host interactions={newPick} sent={sent} persisted={persisted} input={otherDataset} />);
    await screen.findByAltText('Satellite image for tile A');
    fireEvent.load(screen.getByAltText('Satellite image for tile A'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save network' })).toBeEnabled());
  } finally { global.fetch = previousFetch; }
});

test('a neighbor without imagery remains editable and does not request an image', async () => {
  const previousFetch = global.fetch;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [] }) })) as unknown as typeof fetch;
  try {
    const sent = jest.fn();
    const view = render(<Host interactions={mapPick(1)} sent={sent} persisted={jest.fn()} />);
    await screen.findByAltText('Satellite image for tile B');
    fireEvent.load(screen.getByAltText('Satellite image for tile B'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Navigate east' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Navigate east' }));
    await waitFor(() => expectTileSummary('C', 0, 0));
    expect(screen.getByText(/Imagery unavailable for this tile/)).toBeInTheDocument();
    expect(screen.queryByAltText('Satellite image for tile C')).not.toBeInTheDocument();
    expect(view.container.querySelector('svg[aria-label="Sidewalk tile image and network"]')).toBeTruthy();
  } finally { global.fetch = previousFetch; }
});
