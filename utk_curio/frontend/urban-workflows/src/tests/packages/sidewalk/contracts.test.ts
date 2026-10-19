import * as fs from 'fs';
import * as path from 'path';
const { latestAutkSelection } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/autkSelection');
const { makeNetworkEditEnvelope, isSidewalkNetworkEdit, SIDEWALK_NETWORK_EDIT_CHANNEL } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/networkEditContract');
const { buildEditProvenance } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/provenance');
import type { FeatureCollection } from 'geojson';

const before: FeatureCollection = { type: 'FeatureCollection', features: [
  { type: 'Feature', id: 'a', properties: {}, geometry: { type: 'LineString', coordinates: [[0, 0], [1, 0]] } },
] };
const after: FeatureCollection = { type: 'FeatureCollection', features: [
  { type: 'Feature', id: 'a', properties: {}, geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] } },
] };

describe('Sidewalk interaction and provenance contracts', () => {
  it('reads current Autark row selections and chooses the latest highest-priority event', () => {
    expect(latestAutkSelection([
      { priority: 0, details: { autk_selection: { data: [1], layerRef: 'tiles' } } },
      { priority: 1, details: { autk_selection: { data: [2], layerRef: 'tiles' } } },
    ])).toMatchObject({ indices: [2], kind: 'legacy', activeIndex: null, candidateIndices: [], featureId: null, feature: null, layerRef: 'tiles' });
    expect(latestAutkSelection([{ details: { unrelated: true } }])).toBeNull();
  });

  it('keeps PCP candidates separate from the one active map pick', () => {
    const event = (data: number[], selectionOrigin: object) => [
      { details: { autk_selection: { data, priority: 1, selectionOrigin } } },
    ];
    expect(latestAutkSelection(event([1, 4, 7], { version: 1, kind: 'plot-brush', candidateIndices: [1, 4, 7] })))
      .toMatchObject({ kind: 'plot-brush', indices: [1, 4, 7], candidateIndices: [1, 4, 7], activeIndex: null });
    expect(latestAutkSelection(event([1, 4], { version: 1, kind: 'map-pick', activeIndex: 4 })))
      .toMatchObject({ kind: 'map-pick', indices: [1, 4], activeIndex: 4 });
    expect(latestAutkSelection(event([], { version: 1, kind: 'map-pick', activeIndex: null })))
      .toMatchObject({ kind: 'map-pick', activeIndex: null });
  });

  it('emits a typed versioned edit envelope and reproducible provenance', () => {
    const provenance = buildEditProvenance({ tileId: 'tile-7', operations: ['move_node', 'draw_edge'], before, after, editRevision: 3, validationWarnings: ['warning'] });
    const edit = makeNetworkEditEnvelope({ tileId: 'tile-7', editRevision: 3, operationTypes: ['move_node', 'draw_edge'], tileFeature: { type: 'Feature', properties: { tile_id: 'tile-7' }, geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] } }, before, after, provenance });
    expect(SIDEWALK_NETWORK_EDIT_CHANNEL).toBe('sidewalk.network-edit');
    expect(isSidewalkNetworkEdit(edit)).toBe(true);
    expect(provenance).toMatchObject({ selectedTileId: 'tile-7', editRevision: 3, validationWarnings: ['warning'], affectedFeatureIds: ['a'] });
    expect(provenance.operations).toEqual([{ sequence: 1, type: 'move_node' }, { sequence: 2, type: 'draw_edge' }]);
    expect(provenance.sourceRevision).toMatch(/^fnv1a32:/);
    expect(provenance.before).toEqual(before);
    expect(provenance.after).toEqual(after);
    expect(typeof provenance.timestamp).toBe('string');
  });

});
