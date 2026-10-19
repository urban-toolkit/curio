import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Harness, ready, network, tile } from '../../_support/sidewalkEditorHarness';
const originalFetch = global.fetch;
afterEach(() => { global.fetch = originalFetch; });
const response = (west = 0) => ({ ok: true, json: async () => network(west) });

test('network failure clears A geometry and disables Save for B, then recovers on A', async () => {
  global.fetch = jest.fn(async (url: string) => url.includes('network-B') ? { ok: false, status: 404 } : response()) as unknown as typeof fetch;
  const overlapping = { type: 'FeatureCollection' as const, features: [tile('A'), tile('B')] };
  const emit = jest.fn(); const view = render(<Harness input={overlapping} initialConfig={{}} emit={emit} />);
  await ready();
  view.rerender(<Harness input={overlapping} index={1} initialConfig={{}} emit={emit} />);
  await screen.findByText(/Network data could not be loaded/);
  expect(screen.getByRole('button', { name: 'Save network' })).toBeDisabled();
  expect(view.container.querySelector('svg[viewBox="0 0 1000 1000"]')).toBeNull();
  expect(screen.getByText("Tile B")).toBeInTheDocument();
  expect(screen.getByText('No network loaded')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Save network' })); expect(emit).not.toHaveBeenCalled();
  view.rerender(<Harness input={overlapping} index={0} initialConfig={{}} emit={emit} />); await ready();
});

test('Save waits for the current image; image error disables editing and a new tile recovers', async () => {
  global.fetch = jest.fn(async (url: string) => response(url.includes('network-B') ? 1 : 0)) as unknown as typeof fetch;
  const view = render(<Harness initialConfig={{}} />);
  const firstImage = await screen.findByAltText('Satellite image for tile A');
  await screen.findByText('Tile A');
  expect(screen.getByRole('button', { name: 'Save network' })).toBeDisabled();
  fireEvent.error(firstImage);
  expect(screen.getByRole('alert')).toHaveTextContent('Tile image could not be loaded');
  fireEvent.load(firstImage); // A late image-load event cannot clear the error.
  expect(screen.getByRole('button', { name: 'Save network' })).toBeDisabled();
  view.rerender(<Harness index={1} initialConfig={{}} />);
  fireEvent.load(firstImage); // Detached old element must not ready B.
  await screen.findByAltText('Satellite image for tile B');
  expect(screen.getByRole('button', { name: 'Save network' })).toBeDisabled();
  await ready('B');
});

test('a declared missing image leaves network editing and Save available', async () => {
  global.fetch = jest.fn(async () => response()) as unknown as typeof fetch;
  const missing = tile('A');
  missing.properties = { ...missing.properties, image_available: false };
  const emit = jest.fn();
  const view = render(<Harness input={{ type: 'FeatureCollection', features: [missing] }} initialConfig={{}} emit={emit} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save network' })).toBeEnabled());
  expect(screen.queryByAltText('Satellite image for tile A')).toBeNull();
  expect(screen.getByText(/Imagery unavailable for this tile/)).toBeInTheDocument();
  expect(view.container.querySelector('svg[viewBox="0 0 1000 1000"]')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Save network' }));
  expect(emit.mock.calls.at(-1)![0].data.features).toHaveLength(1);
});

test('the editing canvas follows the loaded image aspect ratio while keeping the SVG aligned', async () => {
  global.fetch = jest.fn(async () => response()) as unknown as typeof fetch;
  const view = render(<Harness initialConfig={{}} />);
  const image = await screen.findByAltText('Satellite image for tile A');
  Object.defineProperties(image, {
    naturalWidth: { configurable: true, value: 512 },
    naturalHeight: { configurable: true, value: 256 },
  });
  fireEvent.load(image);
  await waitFor(() => expect(image.parentElement).toHaveStyle({ aspectRatio: '2' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save network' })).toBeEnabled());
  expect(view.container.querySelector('svg[aria-label="Sidewalk tile image and network"]')).toHaveStyle({ width: '100%', height: '100%' });
});

test('rapid A→B aborts A; a stale A response cannot overwrite B, and network readiness gates Save', async () => {
  let resolveA!: (value: ReturnType<typeof response>) => void;
  let resolveB!: (value: ReturnType<typeof response>) => void;
  const fetchMock = jest.fn((url: string) => new Promise<ReturnType<typeof response>>(resolve => {
    if (url.includes('network-A')) resolveA = resolve; else resolveB = resolve;
  }));
  global.fetch = fetchMock as unknown as typeof fetch;
  const emit = jest.fn(); const view = render(<Harness initialConfig={{}} emit={emit} />);
  fireEvent.load(await screen.findByAltText('Satellite image for tile A'));
  expect(screen.getByRole('button', { name: 'Save network' })).toBeDisabled();
  view.rerender(<Harness index={1} initialConfig={{}} emit={emit} />);
  fireEvent.load(await screen.findByAltText('Satellite image for tile B'));
  const signal = (fetchMock.mock.calls[0] as unknown[])[1] as { signal: AbortSignal };
  expect(signal.signal.aborted).toBe(true);
  await act(async () => { resolveB(response(1)); });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save network' })).toBeEnabled());
  await act(async () => { resolveA(response()); });
  fireEvent.click(screen.getByRole('button', { name: 'Save network' }));
  expect(emit.mock.calls.at(-1)![0].data.features[0].geometry.coordinates).toEqual(network(1).features[0].geometry.coordinates);
  expect(emit.mock.calls.at(-1)![0].data.metadata.sidewalkTileId).toBe('B');
});

test('reselecting a committed tile restores its draft and exact committed envelope', async () => {
  const persist = jest.fn(); const interaction = jest.fn();
  const view = render(<Harness onPersist={persist} interaction={interaction} />);
  await ready(); fireEvent.click(screen.getByRole('button', { name: 'Save network' }));
  const committed = persist.mock.calls.at(-1)![0].byTile.A.committedEdit;
  view.rerender(<Harness index={1} onPersist={persist} interaction={interaction} />); await ready('B');
  view.rerender(<Harness index={0} onPersist={persist} interaction={interaction} />); await ready();
  expect(interaction.mock.calls.at(-1)![0]['sidewalk.network-edit']).toEqual(committed);
});
