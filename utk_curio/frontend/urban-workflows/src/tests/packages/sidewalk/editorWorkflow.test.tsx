import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const { SidewalkTileEditor, parseSidewalkEditConfig } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/SidewalkTileEditor');

const tile = {
  type: 'Feature', properties: { tile_id: '1_2', network_url: 'network-1_2.geojson', image_url: 'data:image/jpeg;base64,AA==' },
  geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] },
};
const network = {
  type: 'FeatureCollection', features: [{ type: 'Feature', id: 'edge-1', properties: {},
    geometry: { type: 'LineString', coordinates: [[0.1, 0.1], [0.9, 0.9]] } }],
};

test('selects one tile, shows its clipped network, and saves a versioned edit downstream', async () => {
  const persist = jest.fn();
  const emit = jest.fn();
  const interactionsCallback = jest.fn();
  const config = parseSidewalkEditConfig(JSON.stringify({
    schema: 'curio.sidewalk-tile-edit/v1',
    byTile: { '1_2': { network, originalNetwork: network, past: [], future: [], operations: [] } },
  }));

  render(<SidewalkTileEditor nodeId="tile-edit" input={{ type: 'FeatureCollection', features: [tile] }}
    selectionIndex={0} selectionFeatureId={null} config={config} persist={persist} emit={emit}
    interactionsCallback={interactionsCallback} setStatus={jest.fn()} />);

  await waitFor(() => expect(screen.getByText("Tile 1_2")).toBeInTheDocument());
  fireEvent.load(screen.getByRole('img'));
    fireEvent.click(screen.getByRole('button', { name: 'Save network' }));

  await waitFor(() => expect(interactionsCallback.mock.calls.some(([event]) => event['sidewalk.network-edit'])).toBe(true));
  const [event, nodeId] = interactionsCallback.mock.calls.find(([candidate]) => candidate['sidewalk.network-edit']);
  expect(nodeId).toBe('tile-edit');
  expect(event['sidewalk.network-edit']).toMatchObject({
    schema: 'io.github.lzml0.sidewalk-stewards/network-edit', version: 1,
    tileId: '1_2', editRevision: 1, before: network, after: network,
  });
  expect(persist).toHaveBeenCalledWith(expect.objectContaining({ byTile: expect.objectContaining({ '1_2': expect.objectContaining({ revision: 1, committedNetwork: network, provenance: expect.any(Object) }) }) }));
  expect(emit).toHaveBeenCalledWith(expect.objectContaining({ dataType: 'geodataframe', data: expect.objectContaining({ metadata: expect.objectContaining({ sidewalkTileId: '1_2', provenance: expect.any(Object) }) }) }));
});
