import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Harness, canvas, ready, savedConfig } from '../../_support/sidewalkEditorHarness';
import type { FeatureCollection } from 'geojson';

const original: FeatureCollection = { type: 'FeatureCollection', features: [{
  type: 'Feature', id: 'source-edge', properties: { highway: 'path' },
  geometry: { type: 'LineString', coordinates: [[0.1, 0.1], [0.5, 0.5], [0.9, 0.9]] },
}] };
const initial = () => savedConfig({ network: original, originalNetwork: original });

test('draw snaps to an intermediate Stewards graph vertex at an eight-pixel hit radius', async () => {
  const persist = jest.fn();
  const view = render(<Harness initialConfig={initial()} onPersist={persist} />);
  await ready();
  const beforeDraw = persist.mock.calls.length;
  const svg = canvas(view.container);
  fireEvent.click(screen.getByRole('button', { name: 'Draw edges' }));
  fireEvent.click(svg, { clientX: 506, clientY: 496 });
  fireEvent.click(svg, { clientX: 750, clientY: 750 });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 250)); });
  const stored = persist.mock.calls.at(-1)![0].byTile.A.network;
  expect(stored.features.at(-1).geometry.coordinates[0]).toEqual([0.5, 0.5]);
  expect(stored.features.at(-1).geometry.coordinates[1]).toEqual([0.75, 0.25]);
  expect(persist.mock.calls.at(-1)![0].byTile.A.operations).toEqual(['draw_edge']);
  expect(persist.mock.calls.length).toBe(beforeDraw + 1);
});

test('redrawing an existing polyline segment leaves geometry and history untouched', async () => {
  const persist = jest.fn();
  const view = render(<Harness initialConfig={initial()} onPersist={persist} />);
  await ready();
  const beforeDraw = persist.mock.calls.length;
  const svg = canvas(view.container);
  fireEvent.click(screen.getByRole('button', { name: 'Draw edges' }));
  fireEvent.click(svg, { clientX: 500, clientY: 500 });
  fireEvent.click(svg, { clientX: 900, clientY: 100 });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 250)); });
  expect(persist.mock.calls.length).toBe(beforeDraw);
});

test('Stewards double-click ends a chain without creating its terminal segment', async () => {
  const persist = jest.fn();
  const view = render(<Harness initialConfig={initial()} onPersist={persist} />);
  await ready();
  const svg = canvas(view.container);
  fireEvent.click(screen.getByRole('button', { name: 'Draw edges' }));
  fireEvent.click(svg, { clientX: 200, clientY: 700 });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 250)); });
  fireEvent.click(svg, { clientX: 750, clientY: 750 });
  fireEvent.click(svg, { clientX: 750, clientY: 750 });
  fireEvent.doubleClick(svg, { clientX: 750, clientY: 750 });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 250)); });
  expect(persist.mock.calls.at(-1)![0].byTile.A.operations).toEqual([]);
});

test('Move nodes changes incident geometry as one draft action and undo restores it', async () => {
  const persist = jest.fn();
  const view = render(<Harness initialConfig={initial()} onPersist={persist} />);
  await ready();
  const svg = canvas(view.container);
  fireEvent.click(screen.getByRole('button', { name: 'Move nodes' }));
  const vertex = view.container.querySelector<SVGEllipseElement>('ellipse[cx="500"][cy="500"]');
  expect(vertex).toBeTruthy();
  vertex!.setPointerCapture = jest.fn();
  fireEvent.pointerDown(vertex!, { pointerId: 1, clientX: 500, clientY: 500 });
  fireEvent.pointerMove(svg, { pointerId: 1, clientX: 600, clientY: 400 });
  fireEvent.pointerUp(svg, { pointerId: 1 });
  await waitFor(() => expect(persist.mock.calls.at(-1)?.[0].byTile.A.operations).toEqual(['move_node']));
  expect(persist.mock.calls.at(-1)![0].byTile.A.network.features[0].geometry.coordinates[1]).toEqual([0.6, 0.6]);
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
  expect(persist.mock.calls.at(-1)![0].byTile.A.network.features[0].geometry.coordinates[1]).toEqual([0.5, 0.5]);
});

test('cancelled move leaves the saved draft unchanged', async () => {
  const persist = jest.fn();
  const view = render(<Harness initialConfig={initial()} onPersist={persist} />);
  await ready();
  const svg = canvas(view.container);
  fireEvent.click(screen.getByRole('button', { name: 'Move nodes' }));
  const vertex = view.container.querySelector<SVGEllipseElement>('ellipse[cx="500"][cy="500"]')!;
  vertex.setPointerCapture = jest.fn();
  const before = persist.mock.calls.length;
  fireEvent.pointerDown(vertex, { pointerId: 2, clientX: 500, clientY: 500 });
  fireEvent.pointerMove(svg, { pointerId: 2, clientX: 600, clientY: 400 });
  fireEvent.pointerCancel(svg, { pointerId: 2 });
  expect(persist.mock.calls.length).toBe(before);
  expect(view.container.querySelector<SVGEllipseElement>('ellipse[cx="500"][cy="500"]')).toBeTruthy();
});
