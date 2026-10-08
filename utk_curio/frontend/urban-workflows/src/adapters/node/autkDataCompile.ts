// Pure helpers for the Autark data section: naming the tables a spec asks for,
// resolving its relative file URLs, and compiling it to autk-db JavaScript for
// the Node.js sandbox.
//
// This module deliberately has no imports. It is consumed by the React node
// behavior (autkGrammarBehavior.tsx) and, unchanged, by scripts/compile-autk-data.mts,
// which Node runs directly with type stripping so the CI stress harness can
// produce the very same JavaScript the browser would post to the backend.

// Stand-in for "the backend, as reachable from the sandbox" inside a URL that
// will be fetched by the sandbox's Node subprocess.
// ``utk_curio/sandbox/app/worker.py::execute_js_code`` replaces it with the
// backend's real base URL at execution time.
//
// Why a token rather than a URL: the browser cannot know which address that
// subprocess must use. The two run in different network namespaces whenever
// Curio is containerised (a host-published 5022 is still 5002 inside), so the
// port the page was served against is not usable there - and neither is any
// constant. This used to force :5002 for a loopback backend, which meant every
// OSM/PBF load on a stack NOT using the default port failed with
// "fetch failed" and silently fell back to the in-browser loader (#248).
// Resolving it in the process that performs the fetch is correct in all three
// cases: default ports, a custom-port stack, and a remapped container port.
export const SANDBOX_BACKEND_URL_TOKEN = '__CURIO_BACKEND_URL__';

// Resolve relative URLs in data source specs to the Curio backend's /file/
// route, which serves files by their path *relative to CURIO_LAUNCH_CWD* — the
// same root and relative-path convention the Python sandbox uses. So users can
// write the CURIO_LAUNCH_CWD-relative path 'my-data/file.pbf' (no host/port, no
// route prefix) exactly as a Python node would read it. The shipped examples'
// 'docs/examples/data/...' extracts come from where Curio keeps them.
// Absolute URIs (http://, https://, data:, blob:, …) are passed through unchanged.
// Applies to all file-URL fields across every data source type.
//
// Rewrite the spec's relative file URLs against `base`. Callers pass the
// host-published backend URL for the browser, or SANDBOX_BACKEND_URL_TOKEN for
// the sandbox - deliberately not a URL, since the sandbox substitutes its own.
// The /file/ route is unauthenticated, so the node fetch needs no token of the
// auth kind.
export function resolveDataSourceUrls(spec: any, base: string): any {
    if (!Array.isArray(spec.data) || spec.data.length === 0) return spec;

    const urlFields = ['pbfFileUrl', 'csvFileUrl', 'jsonFileUrl', 'geojsonFileUrl'];
    const isAbsolute = (url: string) => /^[a-z][a-z\d+\-.]*:/i.test(url);

    const resolved = spec.data.map((source: any) => {
        const patch: Record<string, string> = {};
        for (const field of urlFields) {
            const val = source[field];
            if (typeof val === 'string' && !isAbsolute(val)) {
                patch[field] = `${base}/file/${val.replace(/^\/+/, '')}`;
            }
        }
        return Object.keys(patch).length > 0 ? { ...source, ...patch } : source;
    });

    return { ...spec, data: resolved };
}

// Table names a data spec is contractually asking autk-db to create.
//
// The point is to tell a load that came back SHORT apart from one that came back
// empty. autk-db's `loadOsm` walks `autoLoadLayers.layers` sequentially and lets
// a per-layer failure propagate, so a throw partway leaves the earlier tables
// registered and the later ones absent. A loader that published whatever
// `getLayersMetadata()` holds would surface that downstream as an opaque
// "Table <last layer> not found" from a node two hops away, with the node that
// actually failed showing "Done" (#248), so the loaders check these names.
//
// Naming mirrors autk-db's own, which derives a layer table as
// `outputTableName || `${osmInputTableName}_${layer}``.
export function requestedLayerTables(dataSources: any[]): string[] {
    const names: string[] = [];
    for (const source of dataSources ?? []) {
        const { type, ...rest } = (source ?? {}) as any;
        if (type === 'osm') {
            // Per-layer tables only: autk-db drops the raw OSM import tables
            // once it has extracted the layers.
            const layers = rest?.autoLoadLayers?.layers;
            if (rest?.outputTableName && Array.isArray(layers)) {
                for (const layer of layers) names.push(`${rest.outputTableName}_${layer}`);
            }
        } else if (type === 'geojson' || type === 'csv' || type === 'json') {
            if (rest?.outputTableName) names.push(rest.outputTableName);
        }
        // `join` is skipped on purpose: its MODIFY_ROOT/CREATE_TABLE output
        // rewrites a table another source already created rather than adding a
        // layer of its own, so expecting one would report a phantom miss.
    }
    return Array.from(new Set(names));
}

// A table's rows as Curio hands them to autk-db, which refuses a row whose
// geometry is missing and reads a layer's kind off its first row. A row with no
// geometry gets an empty one, a GeometryCollection with none in it: it loads,
// a map draws nothing for it and a plot still counts it. When the first row has
// no geometry, it trades places with the first row that has one; `order` then
// lists, for each row handed on, the row it was (null when no row moved).
// Every path that loads a table into autk-db goes through this one function: a
// node's inputs (`loadableSource`), and a data section's GeoJSON sources in the
// sandbox (compileDataSpecToAutkDbJs embeds this function's own source) and in
// the browser (loadSpecLayers). So that embedded source runs as it is, the body
// avoids syntax the build compiles to a shared helper (spread, destructuring,
// for...of, optional chaining).
export function loadableFeatures(features: any[]): { features: any[]; order: number[] | null } {
    const has = function (feature: any) { return feature != null && feature.geometry != null; };
    let order: number[] | null = null;
    if (features.length > 0 && !has(features[0])) {
        const first = features.findIndex(has);
        if (first > 0) {
            order = features.map(function (_feature: any, i: number) { return i; });
            order[0] = first;
            order[first] = 0;
        }
    }
    const rows: number[] = order || features.map(function (_feature: any, i: number) { return i; });
    let filled = false;
    const out = rows.map(function (i: number) {
        const feature = features[i];
        if (has(feature)) return feature;
        filled = true;
        return Object.assign({ type: 'Feature', properties: {} }, feature, {
            geometry: { type: 'GeometryCollection', geometries: [] },
        });
    });
    return { features: order || filled ? out : features, order: order };
}

// Compile a grammar `data` section into autk-db JavaScript to run in the backend
// Node.js sandbox. The single top-level `import` is rewritten to `await import()`
// by execute_js_code; the rest is the body of the async function the sandbox
// wraps user code in. Mirrors loadSpecLayers exactly, with the spec inlined as a
// literal and flattenToMultiPolygon inlined (the module-level helper above is not
// in the sandbox's scope). The function returns Array<{name, type, geojson}>,
// which the sandbox persists to DuckDB.
export function compileDataSpecToAutkDbJs(dataSources: any[]): string {
    return `import { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT } from '@urban-toolkit/autk-db';
const __sources = ${JSON.stringify(dataSources)};
// Computed host-side by requestedLayerTables so the naming rules live in ONE
// place rather than being restated inside this emitted string.
const __expectedTables = ${JSON.stringify(requestedLayerTables(dataSources))};
const __loadErrors = [];
// Mirrors joinFailureMessage() host-side; see the throw after the contract check.
const __joinErrors = [];
// loadableFeatures, as the host defines it (autkDataCompile.ts).
const __loadableFeatures = ${loadableFeatures.toString()};
// A GeoJSON source as autk-db loads it: its rows through __loadableFeatures,
// fetched first when the source names a file, as the grammar's own adapter does.
const __loadableGeojson = async (source) => {
  let fc = source.geojsonObject;
  if (fc == null && source.geojsonFileUrl) fc = await (await fetch(source.geojsonFileUrl)).json();
  if (fc == null || !Array.isArray(fc.features)) return source;
  const { geojsonFileUrl: _url, ...rest } = source;
  return { ...rest, geojsonObject: { ...fc, features: __loadableFeatures(fc.features).features } };
};
const db = new AutkDb();
await db.init();
for (const source of __sources) {
  const { type, ...rest } = source ?? {};
  try {
    if (type === 'osm') await db.loadOsm(rest);
    else if (type === 'geojson') await db.loadGeojson(await __loadableGeojson(rest));
    else if (type === 'csv') await db.loadCsv(rest);
    else if (type === 'json') await db.loadJson(rest);
    // In-grammar spatial join between already-loaded tables (sources run in
    // spec order, so the join must come after the tables it references):
    // near: { distance } in workspace meters, groupBy as an array of column specs.
    else if (type === 'join') await db.spatialQuery(rest);
    else console.log('[autk-grammar] unsupported data source type "' + type + '" - skipped');
  } catch (e) {
    // Recorded, not discarded: this reason is the only account of WHY a layer is
    // missing, and the contract check below attaches it to the thrown error.
    __loadErrors.push(type + ': ' + ((e && e.message) || String(e)));
    if (type === 'join') __joinErrors.push((e && e.message) || String(e));
    console.log('[autk-grammar] data load failed for source type "' + type + '": ' + (e && e.message));
  }
}
let __tables = [];
try {
  __tables = db.getLayersMetadata();
} catch (e) {
  // A partially-loaded DB can throw here rather than return [] - treat it as
  // "no usable tables" and let the contract check report it.
  __loadErrors.push('getLayersMetadata: ' + ((e && e.message) || String(e)));
}
const __have = new Set(__tables.map((t) => t.name));
const __missing = __expectedTables.filter((n) => !__have.has(n));
if (__missing.length > 0) {
  const __detail = 'missing: ' + __missing.join(', ')
    + (__loadErrors.length > 0 ? ' (' + __loadErrors.join('; ') + ')' : '');
  if (__loadErrors.length > 0) {
    // Mirrors missingLayerMessage() host-side. Throwing is the whole point: it
    // turns a silent short load into a failed execution, which both reports the
    // real reason on THIS node and lets runDataInBackend's existing retry take a
    // second attempt at what is usually a transient PBF/stream hiccup.
    throw new Error('autk data load produced ' + __missing.length
      + ' fewer table(s) than the spec asked for - ' + __detail);
  }
  console.log('[autk-grammar] ' + __detail
    + ' - no load error recorded, treating as a genuinely empty query area');
}
if (__joinErrors.length > 0) {
  // A join rewrites a table another source created, so the check above never
  // sees one fail; without this a broken join ran silently and the node said
  // Done (#319).
  throw new Error('spatial join failed - ' + __joinErrors.join('; '));
}
const __epsg = String(DEFAULT_WORKSPACE_COORDINATE_FORMAT).match(/(\\d+)/)?.[1] ?? '3395';
// Tag each layer with the CRS its coordinates are ACTUALLY in, detected by
// coordinate magnitude per layer: a layer autk-db projected to the workspace
// CRS is in meters, one it was handed in degrees may still be in degrees. A
// wrong tag silently breaks downstream consumers (the map renderer reads degree
// values as meters near the origin and shows a blank view).
const __layerEpsg = (geojson) => {
  const feats = (geojson && geojson.features) || [];
  for (let i = 0; i < Math.min(feats.length, 5); i++) {
    let c = feats[i] && feats[i].geometry && feats[i].geometry.coordinates;
    while (Array.isArray(c) && Array.isArray(c[0])) c = c[0];
    if (Array.isArray(c) && Number.isFinite(c[0]) && Number.isFinite(c[1])) {
      return (Math.abs(c[0]) <= 180 && Math.abs(c[1]) <= 90) ? '4326' : __epsg;
    }
  }
  return __epsg;
};
const __crsFor = (geojson) => ({ type: 'name', properties: { name: 'urn:ogc:def:crs:EPSG::' + __layerEpsg(geojson) } });
const __flattenToMultiPolygon = (geom) => {
  const polys = [];
  const collect = (g) => {
    if (!g) return;
    if (g.type === 'Polygon') polys.push(g.coordinates);
    else if (g.type === 'MultiPolygon') polys.push(...g.coordinates);
    else if (g.type === 'GeometryCollection') (g.geometries || []).forEach(collect);
  };
  collect(geom);
  return polys.length > 0 ? { type: 'MultiPolygon', coordinates: polys } : null;
};
const __buildingHeight = (props) => {
  const num = (v) => { const n = parseFloat(String(v)); return Number.isFinite(n) && n > 0 ? n : 0; };
  const L = 3.4; // metres per level (matches autk-map's building renderer)
  const p = props || {};
  // autk-map culls a part when its top height <= its base (min_height) — which also
  // covers the no-height case (0 <= 0). Mirror its height computation and, only when
  // the part would be culled, return a height that clears the base by a visible
  // amount; otherwise return null to leave the real tags untouched.
  const base = num(p.min_height) || L * num(p.min_level) || L * num(p['building:min_level']);
  let top = num(p.height) || num(p['building:height']) || L * num(p.levels) || L * num(p['building:levels']);
  if (top === 0 && Array.isArray(p.parts)) {
    for (const q of p.parts) { const h = num(q && q.height) || L * num(q && q.levels); if (h > top) top = h; }
  }
  return top > base ? null : base + 6;
};
const __out = [];
for (const t of __tables) {
  const geojson = await db.getLayer(t.name);
  let type = t.type ?? 'polygons';
  if (type === 'buildings' && Array.isArray(geojson?.features)) {
    // autk-db keeps a building as one GeometryCollection, each part's tags in
    // properties.parts naming its geometry by geometryIndex. Explode each building
    // into one footprint feature per part, carrying that part's tags and height, as
    // explodeBuildingParts does in the browser (autkLayerMaterialize.ts). The
    // downstream loadGeojson('buildings') makes every row a building of its own, so
    // each part also carries, as a property, the building_id it came from. A part's
    // id and geometryIndex are autk-db's bookkeeping and are left out.
    const __exploded = [];
    for (const f of geojson.features) {
      const geom = f && f.geometry;
      const props = (f && f.properties) || {};
      const partMeta = new Map();
      for (const part of Array.isArray(props.parts) ? props.parts : []) {
        if (!part || typeof part !== 'object') continue;
        const { id: _id, geometryIndex, ...tags } = part;
        partMeta.set(geometryIndex, tags);
      }
      const pushPart = (g, meta) => {
        if (!g) return;
        const gg = g.type === 'GeometryCollection' ? __flattenToMultiPolygon(g) : g;
        if (!gg) return;
        const p = { ...(meta || {}) }; delete p.parts;
        if (props.building_id != null) p.building_id = props.building_id;
        const h = __buildingHeight(p); if (h != null) p.height = h;
        __exploded.push({ type: 'Feature', geometry: gg, properties: p });
      };
      if (geom && geom.type === 'GeometryCollection' && Array.isArray(geom.geometries)) {
        geom.geometries.forEach((g, i) => pushPart(g, partMeta.has(i) ? partMeta.get(i) : props));
      } else if (geom) {
        pushPart(geom, props);
      }
    }
    geojson.features = __exploded;
  }
  if (geojson && typeof geojson === 'object') geojson.crs = __crsFor(geojson);
  __out.push({ name: t.name, type, geojson });
}
return __out;`;
}
