const { clipNetworkToBounds, drawNetworkEdge, removeNetworkInsideBounds, validateNetwork } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/sidewalkEditOperations');
import type { FeatureCollection } from 'geojson';

const network: FeatureCollection = {
  type: 'FeatureCollection', features: [{ type: 'Feature', id: 'edge-1', properties: { highway: 'footway' },
    geometry: { type: 'LineString', coordinates: [[-1, 0], [0.5, 0], [2, 0]] } }],
};

describe('Sidewalk network edit operations', () => {
  it('clips source lines to the selected tile and retains an edit identity', () => {
    const clipped = clipNetworkToBounds(network, [0, -1, 1, 1]);
    expect(clipped.features).toHaveLength(1);
    expect(clipped.features[0].id).toBe('edge-1');
    expect(clipped.features[0].geometry).toEqual({ type: 'LineString', coordinates: [[0, 0], [0.5, 0], [1, 0]] });
    expect(validateNetwork(clipped, [0, -1, 1, 1])).toEqual([]);
  });

  it('replaces only tile interior linework and leaves outside linework', () => {
    const outside = removeNetworkInsideBounds(network, [0, -1, 1, 1]);
    expect(outside.features).toHaveLength(2);
    expect(outside.features.map((feature: any) => feature.geometry)).toEqual([
      { type: 'LineString', coordinates: [[-1, 0], [0, 0]] },
      { type: 'LineString', coordinates: [[1, 0], [2, 0]] },
    ]);
  });

  it('draws a minimal sidewalk edge with sidewalk-scale styling metadata', () => {
    const edited = drawNetworkEdge({ type: 'FeatureCollection', features: [] }, [[0, 0], [1, 1]]);
    expect(edited.features[0].properties).toMatchObject({ highway: 'path', source: 'curio-sidewalk-tile-edit', edit: 'draw_edge' });
  });
});


const { moveNetworkNode, splitNetworkEdge, deleteNetworkNode, deleteNetworkNodesInBounds, endpointNodes, networkNodes, connectNetworkNodes } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/sidewalkEditOperations');
const { validateSidewalkTopology } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/sidewalkTopology');
test('moves shared endpoints, splits and deletes without mutating the source', () => {
  const source = drawNetworkEdge({ type: 'FeatureCollection', features: [] }, [[0, 0], [1, 1]]);
  const original = JSON.stringify(source);
  const moved = moveNetworkNode(source, [1, 1], [0.8, 0.8]);
  expect(endpointNodes(moved)).toContainEqual([0.8, 0.8]);
  const split = splitNetworkEdge(moved, 0, 0, [0.4, 0.4]);
  expect(split.features).toHaveLength(2);
  expect(deleteNetworkNode(split, [0.4, 0.4]).features).toHaveLength(0);
  expect(deleteNetworkNodesInBounds(split, [0.3, 0.3, 0.5, 0.5]).features).toHaveLength(0);
  expect(JSON.stringify(source)).toBe(original);
  expect(validateNetwork(moved, [0, 0, 1, 1])).toEqual([]);
});
test('rejects out-of-bounds geometry and identifies topology warnings', () => {
  expect(validateNetwork(network, [0, 0, 1, 1]).length).toBeGreaterThan(0);
  const disconnected = drawNetworkEdge(drawNetworkEdge({ type: 'FeatureCollection', features: [] }, [[0.1, 0.1], [0.3, 0.3]]), [[0.7, 0.7], [0.9, 0.9]]);
  expect(validateSidewalkTopology(disconnected, [0, 0, 1, 1]).length).toBeGreaterThan(0);
});

test('matches Stewards graph adjacency across polyline vertices and does not record a duplicate segment', () => {
  const source: FeatureCollection = { type: 'FeatureCollection', features: [{
    type: 'Feature', id: 'original', properties: {}, geometry: { type: 'LineString', coordinates: [[0, 0], [0.5, 0.5], [1, 1]] },
  }] };
  expect(networkNodes(source)).toEqual([[0, 0], [0.5, 0.5], [1, 1]]);
  expect(endpointNodes(source)).toEqual([[0, 0], [1, 1]]);
  expect(connectNetworkNodes(source, [0.5, 0.5], [1, 1])).toBe(source);
  expect(connectNetworkNodes(source, [1, 1], [0.5, 0.5])).toBe(source);
  const joined = connectNetworkNodes(source, [0, 0], [1, 1]);
  expect(joined.features).toHaveLength(2);
  expect(deleteNetworkNode(joined, [0.5, 0.5]).features.map((feature: any) => feature.id)).toEqual([joined.features[1].id]);
  expect(deleteNetworkNode(joined, [0.25, 0.25])).toBe(joined);
});

test('bulk deletion is one graph operation and a disjoint rectangle is a no-op', () => {
  const source = drawNetworkEdge(drawNetworkEdge({ type: 'FeatureCollection', features: [] }, [[0, 0], [0.5, 0.5]]), [[0.5, 0.5], [1, 1]]);
  expect(deleteNetworkNodesInBounds(source, [2, 2, 3, 3])).toBe(source);
  expect(deleteNetworkNodesInBounds(source, [0.49, 0.49, 0.51, 0.51]).features).toHaveLength(0);
});
