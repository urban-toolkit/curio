/**
 * A grammar after a run, keeping the maps it drew as autk-grammar 5.0.0 does,
 * for the tests of what Curio does with them (adapters/node/autkMapDrawing,
 * autkMapView, autkRasters). `maps` holds the map drawn for each `map` entry
 * of the document, in order. `_layers`, the grammar's private registry, holds
 * one entry for each layer of each map drawn, the maps in order and each
 * map's layers in order: the map, its index, its id (its `id`, else its
 * index), the layer's id there (its `title`, else its `dataRef`), the table it
 * draws and the rows it draws (none here). `mapLayers(dataRef, mapId?)` lists
 * the layers that draw a table, on every map or on the one `mapId` names, and
 * `mapLayer(dataRef, mapId?)` is the last of them. `highlightOnMap` and
 * `clearHighlightOnMap` light and clear those layers through each map's
 * `setHighlightedIds` and `clearHighlightedIds`, as autk-grammar 5.0.0's do,
 * the plots linked to them left out.
 */
export type DrawnLayer = {
  map: any;
  mapIndex: number;
  mapId: string | number;
  layerId: string;
  dataRef: string;
  rows: readonly string[];
};

export type GrammarThatRan = {
  maps: any[];
  _layers: DrawnLayer[];
  mapLayers: (dataRef: string, mapId?: string | number) => Array<{ map: any; layerId: string }>;
  mapLayer: (dataRef: string, mapId?: string | number) => { map: any; layerId: string } | undefined;
  /** Lights *featureIds* on every layer that draws *dataRef*, on every map or on the one *mapId* names. */
  highlightOnMap: (dataRef: string, featureIds: number[], mapId?: string | number) => void;
  /** Clears what every layer that draws *dataRef* lights, on every map or on the one *mapId* names. */
  clearHighlightOnMap: (dataRef: string, mapId?: string | number) => void;
};

/** The id a layer has in its map: its `title`, else its `dataRef`. */
const layerIdOf = (layerRef: any): string =>
  typeof layerRef?.title === "string" && layerRef.title !== "" ? layerRef.title : layerRef?.dataRef;

/** Whether *layer* is on the map *mapId* names: a string by its `id`, a number by its index; without one, every map. */
const isOnMap = (layer: DrawnLayer, mapId?: string | number): boolean =>
  mapId === undefined || (typeof mapId === "number" ? layer.mapIndex === mapId : layer.mapId === mapId);

/**
 * The grammar after it ran *spec* and drew *drawn*, one map for each of its
 * `map` entries. A map not drawn registers no layers, as the grammar keeps a
 * map's layers only once they loaded.
 */
export function grammarThatRan(spec: any, ...drawn: any[]): GrammarThatRan {
  const entries: any[] = spec?.map ? (Array.isArray(spec.map) ? spec.map : [spec.map]) : [];
  const maps: any[] = [];
  const layers: DrawnLayer[] = [];
  entries.forEach((entry, index) => {
    const map = drawn[index];
    if (map) {
      const mapId = entry?.id ?? index;
      for (const layerRef of entry?.layerRefs ?? []) {
        layers.push({ map, mapIndex: index, mapId, layerId: layerIdOf(layerRef), dataRef: layerRef?.dataRef, rows: [] });
      }
    }
    maps[index] = map;
  });
  const mapLayers = (dataRef: string, mapId?: string | number) =>
    layers
      .filter((layer) => layer.dataRef === dataRef && isOnMap(layer, mapId))
      .map(({ map, layerId }) => ({ map, layerId }));
  return {
    maps,
    _layers: layers,
    mapLayers,
    mapLayer: (dataRef, mapId) => mapLayers(dataRef, mapId).pop(),
    highlightOnMap: (dataRef, featureIds, mapId) => {
      for (const { map, layerId } of mapLayers(dataRef, mapId)) map.setHighlightedIds?.(layerId, featureIds);
    },
    clearHighlightOnMap: (dataRef, mapId) => {
      for (const { map, layerId } of mapLayers(dataRef, mapId)) map.clearHighlightedIds?.(layerId);
    },
  };
}
