import React from 'react';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import type { Feature, FeatureCollection, LineString, Polygon } from 'geojson';
const { SidewalkTileEditor, parseSidewalkEditConfig } = require('../../../../../../packages/curio.sidewalk-stewards@1/sources/SidewalkTileEditor');

export const tile = (id: string, west = 0): Feature<Polygon> => ({
  type: 'Feature', properties: { tile_id: id, image_url: `image-${id}.png`, network_url: `network-${id}.geojson` },
  geometry: { type: 'Polygon', coordinates: [[[west, 0], [west + 1, 0], [west + 1, 1], [west, 1], [west, 0]]] },
});
export const network = (west = 0): FeatureCollection<LineString> => ({ type: 'FeatureCollection', features: [
  { type: 'Feature', id: 'edge', properties: {}, geometry: { type: 'LineString', coordinates: [[west + 0.1, 0.1], [west + 0.9, 0.9]] } },
] });
export const tiles: FeatureCollection = { type: 'FeatureCollection', features: [tile('A'), tile('B', 1)] };
export const savedConfig = (extra: Record<string, unknown> = {}) => ({ schema: 'curio.sidewalk-tile-edit/v1', byTile: {
  A: { network: network(), originalNetwork: network(), past: [], future: [], operations: [], ...extra },
  B: { network: network(1), originalNetwork: network(1), past: [], future: [], operations: [] },
} });
export function Harness({ index = 0, initialConfig = savedConfig(), emit = jest.fn(), interaction = jest.fn(), onPersist = jest.fn(), id = 'test', input = tiles }:
  { index?: number; initialConfig?: unknown; emit?: jest.Mock; interaction?: jest.Mock; onPersist?: jest.Mock; id?: string; input?: FeatureCollection }) {
  const [config, setConfig] = React.useState(() => parseSidewalkEditConfig(initialConfig));
  return <SidewalkTileEditor nodeId={id} input={input} selectionIndex={index} allowSingleTile={false}
    selectionFeatureId={null} config={config} persist={(next: typeof config) => { onPersist(next); setConfig(next); }}
    emit={emit} interactionsCallback={interaction} setStatus={jest.fn()} />;
}
export async function ready(id = 'A') {
  const image = await screen.findByAltText(`Satellite image for tile ${id}`);
  fireEvent.load(image);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save network' })).toBeEnabled());
}
export function canvas(container: HTMLElement): SVGSVGElement {
  const element = container.querySelector<SVGSVGElement>('svg[viewBox="0 0 1000 1000"]');
  if (!element) throw new Error('Ready editor canvas missing');
  jest.spyOn(element, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, top: 0, left: 0, right: 1000, bottom: 1000, width: 1000, height: 1000, toJSON: () => ({}) });
  return element;
}
export async function draw(element: SVGSVGElement) {
  fireEvent.click(screen.getByRole('button', { name: 'Draw edges' }));
  fireEvent.click(element, { clientX: 200, clientY: 700 });
  fireEvent.click(element, { clientX: 700, clientY: 300 });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 250)); });
}
