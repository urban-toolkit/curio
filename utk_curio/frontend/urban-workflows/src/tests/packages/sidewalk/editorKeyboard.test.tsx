import React from 'react';
import { act, fireEvent, render, screen, within, waitFor } from '@testing-library/react';
import { Harness, canvas } from '../../_support/sidewalkEditorHarness';

test('shortcuts stay within one focused editor and do not intercept editable controls or document events', async () => {
  const view = render(<><Harness id="one" /><Harness id="two" /></>);
  const first = view.container.querySelector<HTMLElement>('[data-curio-sidewalk-editor="one"]')!;
  const second = view.container.querySelector<HTMLElement>('[data-curio-sidewalk-editor="two"]')!;
  for (const region of [first, second]) {
    fireEvent.load(await within(region).findByRole('img'));
    await waitFor(() => expect(within(region).getByRole('button', { name: 'Save network' })).toBeEnabled());
  }
  first.focus(); fireEvent.keyDown(first, { key: 'l' });
  expect(within(first).getByRole('button', { name: 'Cancel edge drawing' })).toBeInTheDocument();
  expect(within(second).getByRole('button', { name: 'Draw edges' })).toBeInTheDocument();
  const svg = canvas(first);
  fireEvent.click(svg, { clientX: 200, clientY: 700 }); fireEvent.click(svg, { clientX: 700, clientY: 300 });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 250)); });
  expect(within(first).getByText(/2 lines/)).toBeInTheDocument();
  fireEvent.keyDown(first, { key: 'z', ctrlKey: true });
  expect(within(first).getByText(/1 lines/)).toBeInTheDocument();
  expect(within(second).getByText(/1 lines/)).toBeInTheDocument();
  fireEvent.keyDown(first, { key: 'z', ctrlKey: true, shiftKey: true });
  expect(within(first).getByText(/2 lines/)).toBeInTheDocument();
  fireEvent.click(within(first).getByRole('button', { name: 'Data sources' }));
  const sources = within(first).getByRole('dialog', { name: 'Data sources' });
  fireEvent.keyDown(sources, { key: 'd' });
  expect(within(first).getByRole('button', { name: 'Delete' })).toBeInTheDocument();
  fireEvent.keyDown(sources, { key: 'Escape' });
  expect(within(first).queryByRole('dialog', { name: 'Data sources' })).not.toBeInTheDocument();
  second.focus(); fireEvent.keyDown(document, { key: 'l' });
  expect(within(second).getByRole('button', { name: 'Draw edges' })).toBeInTheDocument();
  fireEvent.keyDown(second, { key: 'd' });
  expect(within(second).getByRole('button', { name: 'Delete' })).toHaveAttribute('aria-pressed', 'true');
  view.unmount(); fireEvent.keyDown(document, { key: 'z', ctrlKey: true });
});


test('pointer editing moves and snaps endpoints, splits edges, and deletes selected nodes', async () => {
  const pointer = Object.getOwnPropertyDescriptor(window, 'PointerEvent');
  const capture = Object.getOwnPropertyDescriptor(SVGElement.prototype, 'setPointerCapture');
  Object.defineProperty(window, 'PointerEvent', { configurable: true, value: MouseEvent });
  Object.defineProperty(SVGElement.prototype, 'setPointerCapture', { configurable: true, value: jest.fn() });
  try {
    const initial = { schema: 'curio.sidewalk-tile-edit/v1', byTile: { A: {
      originalNetwork: { type: 'FeatureCollection', features: [] },
      network: { type: 'FeatureCollection', features: [
        { type: 'Feature', id: 'one', properties: {}, geometry: { type: 'LineString', coordinates: [[0.1, 0.1], [0.3, 0.3]] } },
        { type: 'Feature', id: 'two', properties: {}, geometry: { type: 'LineString', coordinates: [[0.5, 0.5], [0.9, 0.9]] } },
      ] }, past: [], future: [], operations: [],
    } } };
    const emit = jest.fn(); const view = render(<Harness initialConfig={initial} emit={emit} />);
    fireEvent.load(await screen.findByRole('img'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save network' })).toBeEnabled());
    const svg = canvas(view.container);
    expect(svg.querySelector('[data-testid="sidewalk-network-node"]')?.getAttribute('rx')).toBe('10');
    expect(svg.querySelector('[data-testid="sidewalk-network-node"]')?.getAttribute('ry')).toBe('10');
    jest.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, top: 0, left: 0, right: 800, bottom: 500, width: 800, height: 500, toJSON: () => ({}) });
    act(() => { window.dispatchEvent(new Event('resize')); });
    await waitFor(() => expect(svg.querySelector('[data-testid="sidewalk-network-node"]')?.getAttribute('ry')).toBe('16'));
    expect(svg.querySelector('[data-testid="sidewalk-network-node"]')?.getAttribute('rx')).toBe('10');
    jest.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, top: 0, left: 0, right: 1000, bottom: 1000, width: 1000, height: 1000, toJSON: () => ({}) });
    act(() => { window.dispatchEvent(new Event('resize')); });
    fireEvent.pointerDown(svg.querySelectorAll('[data-testid="sidewalk-network-node"]')[1], { pointerId: 1, clientX: 300, clientY: 700 });
    fireEvent.pointerMove(svg, { pointerId: 1, clientX: 506, clientY: 498 });
    fireEvent.pointerUp(svg, { pointerId: 1 });
    fireEvent.click(screen.getByRole('button', { name: 'Save network' }));
    expect(emit.mock.calls.at(-1)![0].data.features[0].geometry.coordinates[1]).toEqual([0.5, 0.5]);
    fireEvent.contextMenu(svg, { button: 2, clientX: 700, clientY: 300 });
    expect(screen.getByText(/3 lines/)).toBeInTheDocument();
    fireEvent.pointerDown(svg.querySelectorAll('[data-testid="sidewalk-network-node"]')[0], { pointerId: 1, clientX: 100, clientY: 900 });
    fireEvent.keyDown(view.container.querySelector('[data-curio-sidewalk-editor="test"]')!, { key: 'Delete' });
    expect(screen.getByText(/2 lines/)).toBeInTheDocument();
  } finally {
    if (pointer) Object.defineProperty(window, 'PointerEvent', pointer); else Reflect.deleteProperty(window, 'PointerEvent');
    if (capture) Object.defineProperty(SVGElement.prototype, 'setPointerCapture', capture); else Reflect.deleteProperty(SVGElement.prototype, 'setPointerCapture');
  }
});
