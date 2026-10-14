/**
 * A grammar after a run, keeping the maps it drew as autk-grammar 4.2.0 does,
 * for the tests of what Curio does with them (adapters/node/autkMapDrawing,
 * autkMapView, autkRasters). `maps` holds the map drawn for each `map` entry
 * of the document, in order. `mapLayer(dataRef)` finds the layer a map draws
 * for a table: the last map that draws it, and the layer's id there, its
 * `title`, else its `dataRef`. `_mapRegistry`, the grammar's private registry,
 * holds one map for each table a layerRef names, the last map that draws it.
 */
export type GrammarThatRan = {
  maps: any[];
  _mapRegistry: Map<string, any>;
  mapLayer: (dataRef: string) => { map: any; layerId: string } | undefined;
};

/** The id a layer has in its map: its `title`, else its `dataRef`. */
const layerIdOf = (layerRef: any): string =>
  typeof layerRef?.title === "string" && layerRef.title !== "" ? layerRef.title : layerRef?.dataRef;

/** The grammar after it ran *spec* and drew *drawn*, one map for each of its `map` entries. */
export function grammarThatRan(spec: any, ...drawn: any[]): GrammarThatRan {
  const entries: any[] = spec?.map ? (Array.isArray(spec.map) ? spec.map : [spec.map]) : [];
  const maps: any[] = [];
  const registry = new Map<string, any>();
  const layerIds = new Map<string, string>();
  entries.forEach((entry, index) => {
    const map = drawn[index];
    for (const layerRef of entry?.layerRefs ?? []) {
      registry.set(layerRef?.dataRef, map);
      layerIds.set(layerRef?.dataRef, layerIdOf(layerRef));
    }
    maps[index] = map;
  });
  return {
    maps,
    _mapRegistry: registry,
    mapLayer: (dataRef) => {
      const map = registry.get(dataRef);
      return map ? { map, layerId: layerIds.get(dataRef) ?? dataRef } : undefined;
    },
  };
}
