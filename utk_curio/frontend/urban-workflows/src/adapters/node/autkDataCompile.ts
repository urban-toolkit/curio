// Pure helpers for the Autark data section: naming the tables a spec asks for,
// resolving its relative file URLs, and compiling it to autk-db JavaScript for
// the Node.js sandbox.
//
// This module deliberately has no imports. It is consumed by the React node
// behavior (autkGrammarBehavior.tsx), by the compiler a run on the server uses
// (autkDataCompileServer.ts, bundled into dist/autk-data-compile.cjs), and,
// unchanged, by scripts/compile-autk-data.mts, which Node runs directly with
// type stripping so the CI stress harness can produce the very same JavaScript
// the browser would post to the backend.

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

// autk-db's default workspace (its DEFAULT_WORKSPACE_NAME): where a source, a
// pass, a map or a plot that names no `workspace` keeps and reads its tables.
// contracts/autkGrammar.json holds it too, as `defaultWorkspace`, for the
// check of a compute pass over a raster on both sides.
export const AUTK_DEFAULT_WORKSPACE = 'autk';

// The workspace *entry* names (a source, a pass, a map, a plot, or a table a
// node hands on), or undefined for the default one. Only a name other than the
// default's is another workspace; a workspace written null or empty is none.
export function autkWorkspaceOf(entry: any): string | undefined {
    const workspace = entry == null ? undefined : entry.workspace;
    return typeof workspace === 'string' && workspace !== '' && workspace !== AUTK_DEFAULT_WORKSPACE
        ? workspace
        : undefined;
}

// The key a table has where a node tells its tables apart: its name in the
// default workspace, `<workspace>/<name>` in another, so two workspaces can
// hold tables of one name. It is autk-grammar's own `tableKey`, which this
// module, having no imports, writes out; the loaders enter a workspace with
// the grammar's `enterWorkspace`, and the sandbox's loader keys what it read
// back with the grammar's `tableKey`, which the server load's test holds to
// this one (utk_curio/sandbox/tests/test_autk_server_data_load.py).
export function autkTableKey(workspace: string | undefined, name: string): string {
    return workspace === undefined || workspace === AUTK_DEFAULT_WORKSPACE ? name : workspace + '/' + name;
}

// Whether a document keeps tables in another workspace than the default one:
// a source, a compute pass, a map or a plot of *spec* names one. Only then do
// the loaders enter workspaces, with autk-grammar's data entry; a document that
// names none loads in the default workspace alone, as it always has.
export function autkUsesWorkspaces(spec: any): boolean {
    const entries = (held: any): any[] => (held == null ? [] : Array.isArray(held) ? held : [held]);
    return [spec?.data, spec?.compute, spec?.map, spec?.plot]
        .some((held) => entries(held).some((entry) => autkWorkspaceOf(entry) !== undefined));
}

// A data source as the loaders load it: with the workspace it names, the
// default one left out (autkWorkspaceOf).
export function inItsWorkspace(source: any): any {
    if (source == null || typeof source !== 'object' || !('workspace' in source)) return source;
    const workspace = autkWorkspaceOf(source);
    const { workspace: _written, ...rest } = source;
    return workspace === undefined ? rest : { ...rest, workspace };
}

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

    const urlFields = ['pbfFileUrl', 'csvFileUrl', 'jsonFileUrl', 'geojsonFileUrl', 'geotiffFileUrl'];
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

// The source types both loaders hand to autk-grammar's own data adapter
// (`createDataAdapter().resolveSource`), which loads them as the grammar does,
// each loader taking it from the grammar's `./data` entry, which imports
// autk-db alone. Each makes a raster table, a heatmap with autk-db's
// `buildHeatmap` and a GeoTIFF with its `loadGeoTiff`, which the loaders read
// back with the grid its cells lie on (withRasterGrid) and hand on as Curio
// hands on a raster (rasterEnvelope). contracts/autkGrammar.json holds this
// list too, as `rasterSources`.
export const GRAMMAR_RASTER_SOURCES = ['heatmap', 'geotiff'];

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
// `outputTableName || `${osmInputTableName}_${layer}``. Each table is named by
// its key (autkTableKey), in the workspace its source loads it into. A
// heatmap's or a GeoTIFF's raster table is one of them: the loaders read it
// back by its key.
export function requestedLayerTables(dataSources: any[]): string[] {
    const names: string[] = [];
    for (const source of dataSources ?? []) {
        const { type, ...rest } = (source ?? {}) as any;
        const workspace = autkWorkspaceOf(rest);
        if (type === 'osm') {
            // Per-layer tables only: autk-db drops the raw OSM import tables
            // once it has extracted the layers.
            const layers = rest?.autoLoadLayers?.layers;
            if (rest?.outputTableName && Array.isArray(layers)) {
                for (const layer of layers) names.push(autkTableKey(workspace, `${rest.outputTableName}_${layer}`));
            }
        } else if (type === 'geojson' || type === 'csv' || type === 'json' || GRAMMAR_RASTER_SOURCES.includes(type)) {
            if (rest?.outputTableName) names.push(autkTableKey(workspace, rest.outputTableName));
        }
        // `join` is skipped on purpose: its MODIFY_ROOT/CREATE_TABLE output
        // rewrites a table another source already created rather than adding a
        // layer of its own, so expecting one would report a phantom miss.
    }
    return Array.from(new Set(names));
}

// A table a data section's heatmap or join reads: its name, the workspace of
// the entry that reads it, its key there (autkTableKey), the entry's place in
// the section, and the words that name the entry when the table is missing. A
// heatmap bins its `joinDataRef`; a join reads its `dataRef`, the table that
// receives the joined columns, and its `joinDataRef`, the table joined onto it.
type SectionRead = { at: number; name: string; workspace?: string; key: string; reader: string };

function sectionReads(dataSources: any[]): SectionRead[] {
    const sources: any[] = Array.isArray(dataSources) ? dataSources : [];
    const named = (table: unknown): table is string => typeof table === 'string' && table !== '';
    const reads: SectionRead[] = [];
    sources.forEach((source, at) => {
        const workspace = autkWorkspaceOf(source);
        const read = (name: string, reader: string) => reads.push({
            at, name, ...(workspace ? { workspace } : {}), key: autkTableKey(workspace, name), reader,
        });
        if (source?.type === 'heatmap' && named(source.joinDataRef)) {
            read(source.joinDataRef, `The heatmap "${autkTableKey(workspace, source.outputTableName)}" bins`);
        } else if (source?.type === 'join') {
            const reader = `The join of "${autkTableKey(workspace, source.joinDataRef)}" onto `
                + `"${autkTableKey(workspace, source.dataRef)}" reads`;
            for (const table of [source.dataRef, source.joinDataRef]) {
                if (named(table)) read(table, reader);
            }
        }
    });
    return reads;
}

// Why a data section's heatmap or join cannot run, or null: it reads a table
// one of the section's own sources loads only after it. Both loaders fail with
// these words before they load anything (the sandbox's code throws them, as
// computed here). A table no source of the section loads is one the node's
// input carries (sectionInputTables). A table in another workspace than the
// default one is named by its key (autkTableKey), as the load contract names it.
export function sectionTableProblem(dataSources: any[]): string | null {
    const sources: any[] = Array.isArray(dataSources) ? dataSources : [];
    for (const read of sectionReads(sources)) {
        if (requestedLayerTables(sources.slice(0, read.at)).includes(read.key)) continue;
        if (requestedLayerTables(sources.slice(read.at + 1)).includes(read.key)) {
            return `${read.reader} "${read.key}" before its data section loads that table: `
                + `list the source of "${read.key}" first.`;
        }
    }
    return null;
}

// A table of the node's input that a data section's heatmap or join reads: its
// name and the workspace of the entry that reads it first, `before`, that
// entry's place, where both loaders load it into the section's database, and
// what the load fails with when the input does not carry it.
export type SectionInputTable = { name: string; workspace?: string; before: number; missing: string };

// The tables a data section's heatmaps and joins read that none of its own
// sources loads, which the node's input carries, each once, by key, in the
// order the section first reads them. A section's own are the tables its
// sources load and make (requestedLayerTables) and every name a source of it
// gives its table (`outputTableName`, an OSM load's included). The input names
// them as the node reads its input everywhere (utils/autkInput
// autkSourcesFrom): `input_<k>` for what arrives on circle k, a layer by its
// own name. A section that reads none of them reads no input.
export function sectionInputTables(dataSources: any[]): SectionInputTable[] {
    const sources: any[] = Array.isArray(dataSources) ? dataSources : [];
    const loaded = new Set([
        ...requestedLayerTables(sources),
        ...sources
            .filter((source) => typeof source?.outputTableName === 'string' && source.outputTableName !== '')
            .map((source) => autkTableKey(autkWorkspaceOf(source), source.outputTableName)),
    ]);
    const seen = new Set<string>();
    const tables: SectionInputTable[] = [];
    for (const read of sectionReads(sources)) {
        if (loaded.has(read.key) || seen.has(read.key)) continue;
        seen.add(read.key);
        tables.push({
            name: read.name,
            ...(read.workspace ? { workspace: read.workspace } : {}),
            before: read.at,
            missing: `${read.reader} "${read.key}", a table its data section does not load `
                + `and the node's input does not carry.`,
        });
    }
    return tables;
}

// The keys of the tables a data section's joins write their columns onto
// (their `dataRef`): an input table one of them names is what the join made,
// so the section hands it on (handedOn).
export function sectionJoinRoots(dataSources: any[]): string[] {
    const sources: any[] = Array.isArray(dataSources) ? dataSources : [];
    return Array.from(new Set(sources
        .filter((source) => source?.type === 'join' && typeof source.dataRef === 'string' && source.dataRef !== '')
        .map((source) => autkTableKey(autkWorkspaceOf(source), source.dataRef))));
}

// The input tables a data section reads (sectionInputTables, *wanted*), found
// in the inputs a JavaScript run is given, `{input_0: ..., input_1: ...}`, as
// the sandbox hands them to node code (sandbox/app/worker.py `_to_js_value`):
// a GeoDataFrame as a FeatureCollection that carries its layer's `name`,
// `workspace` and `layerType`, an Autark node's layer list as its records
// (`{name, type, geojson, workspace}`), the frames side by side of a tuple or
// a list, and a dict of frames by key. Each is named as the node names its
// input (utils/autkInput autkSourcesFrom): a layer by its own name, the first
// input that brings a name keeping it; a frame with no name `input_<k>` after
// its circle (`input_<k>_1`, ... for the next ones on that circle); and
// `input_<k>` also names an input of one named layer, unless a table already
// has that name. One input of frames side by side is read as the node reads it:
// each frame on a circle of its own, by its place. Tables are told apart by
// key, in the workspace each names. A raster is no table a heatmap bins or a
// join reads. A table the inputs do not carry fails with its `missing` words,
// before anything is loaded. Returns each table's name, workspace, layer type,
// rows and `before`. Both loaders' sandbox code embeds this function's source
// (compileDataSpecToAutkDbJs), so the body avoids what loadableFeatures and
// withOsmIds avoid.
export function inputTablesFrom(inputs: any, wanted: SectionInputTable[]): any[] {
    const isPlain = function (value: any) { return Object.prototype.toString.call(value) === '[object Object]'; };
    const isCollection = function (value: any) {
        return isPlain(value) && value.type === 'FeatureCollection' && Array.isArray(value.features);
    };
    const text = function (value: any) { return typeof value === 'string' && value !== '' ? value : null; };
    const keyOf = function (workspace: any, name: string) {
        return text(workspace) !== null && workspace !== 'autk' ? workspace + '/' + name : name;
    };
    // The table an item of an input is, or null for anything else.
    const layerOf = function (item: any, named: any): any {
        if (isCollection(item)) {
            return { rows: item, name: text(named) || text(item.name), workspace: text(item.workspace), layerType: text(item.layerType) };
        }
        if (isPlain(item) && isCollection(item.geojson)) {
            return { rows: item.geojson, name: text(item.name), workspace: text(item.workspace), layerType: text(item.type) };
        }
        if (isPlain(item) && item.dataType === 'geodataframe' && isCollection(item.data)) {
            return { rows: item.data, name: text(item.layerName), workspace: text(item.workspace), layerType: text(item.layerType) };
        }
        return null;
    };
    const listOf = function (value: any) {
        return isPlain(value) && value.dataType === 'outputs' && Array.isArray(value.data) ? value.data : value;
    };
    // A dict of frames: its frames, named after their keys; else null.
    const keyedLayers = function (value: any) {
        if (!isPlain(value) || 'dataType' in value || isCollection(value) || isCollection(value.geojson)) return null;
        const layers = Object.keys(value)
            .map(function (key) { return layerOf(value[key], key); })
            .filter(function (layer) { return layer !== null; });
        return layers.length > 0 ? layers : null;
    };
    const layersIn = function (value: any) {
        const held = listOf(value);
        if (Array.isArray(held)) {
            return held.map(function (item: any) { return layerOf(item, null); })
                .filter(function (layer: any) { return layer !== null; });
        }
        const keyed = keyedLayers(held);
        if (keyed !== null) return keyed;
        const one = layerOf(held, null);
        return one === null ? [] : [one];
    };
    const given = isPlain(inputs) ? inputs : {};
    const slots = Object.keys(given)
        .filter(function (key) { return /^input_\d+$/.test(key); })
        .map(function (key) { return Number(key.slice(6)); })
        .sort(function (a, b) { return a - b; });
    let circles: any[] = slots.map(function (slot) { return { at: slot, layers: layersIn(given['input_' + slot]) }; });
    if (slots.length === 1) {
        const held = listOf(given['input_' + slots[0]]);
        const sideBySide = Array.isArray(held) && held.length > 0 && held.every(function (item: any) {
            return (isCollection(item) || (isPlain(item) && item.dataType === 'geodataframe')) && layerOf(item, null) !== null;
        });
        const parts = sideBySide ? held.map(function (item: any) { return layerOf(item, null); }) : keyedLayers(held);
        if (parts !== null) circles = parts.map(function (layer: any, at: number) { return { at: at, layers: [layer] }; });
    }
    const tables: any = {};
    for (let c = 0; c < circles.length; c++) {
        const circle = circles[c];
        for (let l = 0; l < circle.layers.length; l++) {
            const layer = circle.layers[l];
            let name = layer.name || 'input_' + circle.at;
            if (keyOf(layer.workspace, name) in tables) {
                // The name stays the earlier input's layer.
                if (layer.name) continue;
                let n = 1;
                while (keyOf(layer.workspace, name + '_' + n) in tables) n += 1;
                name = name + '_' + n;
            }
            tables[keyOf(layer.workspace, name)] = layer;
        }
    }
    for (let c = 0; c < circles.length; c++) {
        const circle = circles[c];
        if (circle.layers.length !== 1 || !circle.layers[0].name) continue;
        const alias = keyOf(circle.layers[0].workspace, 'input_' + circle.at);
        if (!(alias in tables)) tables[alias] = circle.layers[0];
    }
    return wanted.map(function (table) {
        const layer = tables[keyOf(table.workspace, table.name)];
        if (!layer) throw new Error(table.missing);
        return { name: table.name, workspace: table.workspace, layerType: layer.layerType, rows: layer.rows, before: table.before };
    });
}

// autk-db's `coordinateFormat` for a FeatureCollection, as utils/geoCrs
// `detectCoordinateFormat` gives it: the EPSG code its `crs` names, else
// EPSG:3395 when a coordinate of its first five features lies outside the
// longitude and latitude ranges, else EPSG:4326. The sandbox's code loads an
// input table with it (compileDataSpecToAutkDbJs embeds its source), so the
// body avoids what loadableFeatures avoids.
export function coordinateFormatOf(collection: any): string {
    const crs = collection != null && collection.crs != null && collection.crs.properties != null
        ? collection.crs.properties.name
        : null;
    const declared = typeof crs === 'string' ? crs.match(/EPSG:{1,2}(\d+)/i) : null;
    if (declared) return 'EPSG:' + Number(declared[1]);
    const first = function (held: any): any {
        if (held != null && !Array.isArray(held) && Object.prototype.toString.call(held) === '[object Object]') {
            if (Array.isArray(held.geometries)) {
                for (let i = 0; i < held.geometries.length; i++) {
                    const found = first(held.geometries[i]);
                    if (found) return found;
                }
                return null;
            }
            return held.coordinates !== undefined ? first(held.coordinates) : null;
        }
        if (!Array.isArray(held) || held.length === 0) return null;
        return typeof held[0] === 'number' ? held : first(held[0]);
    };
    const features = collection != null && Array.isArray(collection.features) ? collection.features.slice(0, 5) : [];
    const geometries = features
        .map(function (feature: any) { return feature != null ? feature.geometry : null; })
        .filter(function (geometry: any) { return Boolean(geometry); });
    for (let i = 0; i < geometries.length; i++) {
        const coordinate = first(geometries[i]);
        if (!coordinate) continue;
        const x = coordinate[0];
        const y = coordinate[1];
        if (Number.isFinite(x) && Number.isFinite(y) && (Math.abs(x) > 180 || Math.abs(y) > 90)) return 'EPSG:3395';
    }
    return 'EPSG:4326';
}

// A data section's sources in the order both loaders load them, with the input
// tables it reads (*carried*, each `{before, source}`) each loaded just before
// the first entry that reads it, so the section's own sources keep their order
// and the table its first source loads still gives the workspace its extent.
// Both loaders go through this one function (compileDataSpecToAutkDbJs embeds
// its source), so the body avoids what loadableFeatures avoids.
export function withInputTables(sources: any[], carried: Array<{ before: number; source: any }>): any[] {
    const runs: any[] = [];
    for (let i = 0; i < sources.length; i++) {
        for (let t = 0; t < carried.length; t++) {
            if (carried[t].before === i) runs.push(carried[t].source);
        }
        runs.push(sources[i]);
    }
    return runs;
}

// The tables a data section hands on, by key, as a load that is not read back
// names them: those its own sources load and make (requestedLayerTables), then
// each table of the input a join of it wrote its columns onto (handedOn).
export function sectionTablesHandedOn(dataSources: any[]): string[] {
    const sources: any[] = Array.isArray(dataSources) ? dataSources : [];
    const roots = sectionJoinRoots(sources);
    const joined = sectionInputTables(sources)
        .map((table) => autkTableKey(table.workspace, table.name))
        .filter((key) => roots.includes(key));
    return [...requestedLayerTables(sources), ...joined];
}

// Whether a data section hands on the table of *key*: every table it loads and
// makes, but an input table it loaded (*inputKeys*), which the node's input
// already brings, unless a join wrote its columns onto it (*joinRoots*). Both
// loaders go through this one function (compileDataSpecToAutkDbJs embeds its
// source), so the body avoids what loadableFeatures avoids.
export function handedOn(key: string, inputKeys: string[], joinRoots: string[]): boolean {
    return inputKeys.indexOf(key) < 0 || joinRoots.indexOf(key) >= 0;
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

// What autk-db's `spatialQuery` is handed for a `join` source. The grammar
// names a join's tables `dataRef`, the table that receives the joined columns,
// and `joinDataRef`, the table whose rows are joined onto it; autk-db takes
// them as `tableRootName` and `tableJoinName`. `near` and `groupBy` go with
// them when the source has them, and nothing else does, as the grammar's own
// data adapter hands a join to autk-db. Both loaders go through this one
// function: the sandbox's (compileDataSpecToAutkDbJs embeds its source) and
// the browser's (loadSpecLayers). So that embedded source runs as it is, the
// body avoids what loadableFeatures avoids.
export function joinQueryParams(source: any): {
    tableRootName: string; tableJoinName: string; near?: unknown; groupBy?: unknown;
} {
    const params: any = { tableRootName: source.dataRef, tableJoinName: source.joinDataRef };
    if (source.near) params.near = source.near;
    if (source.groupBy) params.groupBy = source.groupBy;
    return params;
}

// A layer's features as an Autark node hands them on: each OpenStreetMap
// feature with its OSM id in an `osm_id` property, as the Discovery Catalog's
// OpenStreetMap downloads name a row, so a Map Editor node or a selection can
// name it. autk-db gives a road's, a park's or a water's OSM id as the feature's
// GeoJSON `id`, which a table leaves out. A building's `id` is its
// `building_id`, and each of its parts' OSM id is that part's `id` in
// `properties.parts`, so each part gets its own, which it keeps once the
// building is split into a row per part. A feature or a part that has an
// `osm_id` keeps it. A layer from another source, the surface (the area's land,
// no OpenStreetMap element) and a raster come back as they are; the input is
// never changed. Both loaders hand their layers on through this one function:
// the sandbox's (compileDataSpecToAutkDbJs embeds its source) and the browser's
// (loadSpecLayers). So that embedded source runs as it is, the body avoids what
// loadableFeatures avoids, and `typeof` against "object", which the build
// compiles to a shared helper too.
export function withOsmIds(table: { source?: string; type?: string } | null | undefined, features: any[]): any[] {
    if (table == null || table.source !== 'osm' || table.type === 'surface' || table.type === 'raster'
        || !Array.isArray(features)) return features;
    const buildings = table.type === 'buildings';
    const named = function (properties: any, id: any) {
        if (id == null || (properties != null && properties.osm_id != null)) return properties;
        return Object.assign({}, properties, { osm_id: id });
    };
    return features.map(function (feature: any) {
        if (feature == null) return feature;
        const properties = feature.properties;
        if (!buildings) {
            const withId = named(properties, feature.id);
            return withId === properties ? feature : Object.assign({}, feature, { properties: withId });
        }
        if (properties == null || !Array.isArray(properties.parts)) return feature;
        const parts = properties.parts.map(function (part: any) {
            return part == null ? part : named(part, part.id);
        });
        return Object.assign({}, feature, { properties: Object.assign({}, properties, { parts: parts }) });
    });
}

// A raster table's `getRaster` collection with `grid`, the grid its cells lie
// on (utils/raster/rasterWire.ts), which autk-db keeps for no raster it makes.
// A raster's cells lie on a regular grid over the collection's extent,
// `rasterResX` columns by `rasterResY` rows with row 0 at the south edge, in
// `crs`, the CRS of the workspace that made it: a heatmap's are built there,
// and autk-db lays a GeoTIFF's over the file's corners taken into it. The map
// draws them there too. The band arrays are shared, not copied. Both loaders
// go through this one function (compileDataSpecToAutkDbJs embeds its source),
// so the body avoids what loadableFeatures avoids.
export function withRasterGrid(collection: any, crs: string): any {
    const bbox = collection.bbox;
    const properties = collection.features[0].properties;
    const width = properties.rasterResX;
    const height = properties.rasterResY;
    return Object.assign({}, collection, {
        grid: {
            crs: crs,
            width: width,
            height: height,
            originX: bbox[0],
            originY: bbox[3],
            resX: (bbox[2] - bbox[0]) / width,
            resY: (bbox[1] - bbox[3]) / height,
        },
    });
}

// The envelope a raster is handed on in, from node to node and into the
// sandbox's store (utils/raster/rasterWire.ts, whose `encodeRasterEnvelope` is
// this function): its collection with its grid, each band base64 of
// little-endian float32, so a nodata cell (NaN) survives JSON and a Python node
// gets back exactly the values Autark held, and `layerName`, its table's name.
// Both loaders hand a raster on through it (compileDataSpecToAutkDbJs embeds its
// source), so the body avoids what loadableFeatures avoids.
export function rasterEnvelope(collection: any, layerName?: string): any {
    const feature = collection.features[0];
    const properties: any = Object.assign({}, feature.properties);
    const bands: any[] = Array.isArray(properties.bands) ? properties.bands : [];
    for (let b = 0; b < bands.length; b++) {
        const id = String(bands[b].id);
        const values = feature.properties[id];
        const bytes = new Uint8Array(values.length * 4);
        const view = new DataView(bytes.buffer);
        for (let i = 0; i < values.length; i++) view.setFloat32(i * 4, Number(values[i]), true);
        let binary = '';
        for (let i = 0; i < bytes.length; i += 0x8000) {
            binary += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + 0x8000)));
        }
        properties[id] = { float32le: btoa(binary) };
    }
    const envelope: any = {
        dataType: 'raster',
        data: {
            type: 'FeatureCollection',
            bbox: collection.bbox.slice(),
            grid: Object.assign({}, collection.grid),
            features: [{ type: 'Feature', geometry: null, properties: properties }],
        },
    };
    if (layerName) envelope.layerName = layerName;
    return envelope;
}

// The parts of the sandbox's code that differ when a data section names a
// workspace (autkUsesWorkspaces): what it takes from autk-grammar's data entry
// (`enterWorkspace` and `tableKey`), each source loaded in its workspace, each
// workspace's tables read back in turn, with the raster tables it made, and
// each table handed on with its workspace. A data section that names none
// compiles without them, as it always has.
function workspaceCode(uses: boolean) {
    if (!uses) {
        return {
            fromDataEntry: [] as string[],
            skip: '  if (!__handedOn(t.name, __inputKeys, __joinRoots)) continue;',
            load: `  const { type, ...rest } = source ?? {};
  try {`,
            readBack: `let __tables = [];
try {
  __tables = db.getLayersMetadata();
} catch (e) {
  // A partially-loaded DB can throw here rather than return [] - treat it as
  // "no usable tables" and let the contract check report it.
  __loadErrors.push('getLayersMetadata: ' + ((e && e.message) || String(e)));
}
const __have = new Set(__tables.map((t) => t.name).concat(__rasters.map((r) => r.layerName)));`,
            each: 'for (const t of __tables) {',
            handOn: '  __out.push({ name: t.name, type, geojson });',
        };
    }
    return {
        fromDataEntry: ['enterWorkspace', 'tableKey'],
        skip: '  if (!__handedOn(tableKey(workspace, t.name), __inputKeys, __joinRoots)) continue;',
        load: `  const { type, workspace, ...rest } = source ?? {};
  try {
    // Into its workspace, as the grammar's data adapter loads a source:
    // autk-db finds a table in the current workspace only.
    await enterWorkspace(db, workspace);`,
        readBack: `// The tables of each workspace the sources load into, in their order: autk-db
// lists the tables of the current workspace only.
const __workspaces = [...new Set(__sources.map((source) => (source ?? {}).workspace))];
const __tables = [];
for (const workspace of __workspaces) {
  try {
    await enterWorkspace(db, workspace);
    for (const table of db.getLayersMetadata()) __tables.push({ table, workspace });
  } catch (e) {
    // A partially-loaded DB can throw here rather than return [] - treat it as
    // "no usable tables" and let the contract check report it.
    __loadErrors.push('getLayersMetadata: ' + ((e && e.message) || String(e)));
  }
}
const __have = new Set(__tables.map((t) => tableKey(t.workspace, t.table.name))
  .concat(__rasters.map((r) => tableKey(r.workspace, r.layerName))));`,
        each: `for (const { table: t, workspace } of __tables) {
  await enterWorkspace(db, workspace);`,
        handOn: `  // A table in another workspace than the default one says which, so the node
  // it is handed to loads it there.
  __out.push(workspace === undefined ? { name: t.name, type, geojson } : { name: t.name, type, geojson, workspace });`,
    };
}

// Compile a grammar `data` section into autk-db JavaScript to run in the backend
// Node.js sandbox. The top-level `import` is rewritten to `await import()` by
// execute_js_code, and so is autk-grammar's data entry's, the one line that
// imports what the section needs of it: `createDataAdapter` for a source of
// GRAMMAR_RASTER_SOURCES (a heatmap, a GeoTIFF), `enterWorkspace` and
// `tableKey` for a section that names a workspace, and nothing for a section
// with neither. The rest is the body of the async function the sandbox wraps
// user code in. Mirrors loadSpecLayers exactly, with the spec inlined as a
// literal and flattenToMultiPolygon inlined (the module-level helper above is
// not in the sandbox's scope). Each source loads into its workspace, entered
// with the grammar's own `enterWorkspace` (workspaceCode), and a heatmap or a
// GeoTIFF through the grammar's own data adapter. A section whose heatmaps or
// joins read tables of the node's input (sectionInputTables) finds them in the
// inputs the sandbox gives the run, `__inputs` (sandbox/util/js_wrapper.mjs),
// which the node's run in the browser and a run on the server both send, and
// loads each just before the first entry that reads it; one that reads none
// compiles without them. The function returns Array<{name, type, geojson}>,
// each raster table after them in its envelope (rasterEnvelope), each table or
// raster in another workspace than the default one with its `workspace` too,
// which the sandbox persists to DuckDB.
export function compileDataSpecToAutkDbJs(dataSources: any[]): string {
    const sources = (dataSources ?? []).map(inItsWorkspace);
    const parts = workspaceCode(autkUsesWorkspaces({ data: sources }));
    const grammarSources = sources.some((source: any) => GRAMMAR_RASTER_SOURCES.includes(source?.type));
    const fromDataEntry = [...(grammarSources ? ['createDataAdapter'] : []), ...parts.fromDataEntry];
    const dataEntryImport = fromDataEntry.length > 0
        ? `\nimport { ${fromDataEntry.join(', ')} } from '@urban-toolkit/autk-grammar/data';`
        : '';
    const tableCheck = sectionReads(sources).length > 0 ? `// A heatmap or a join that reads a table this section loads only after it
// fails before anything loads, with the words the host gives it
// (sectionTableProblem).
const __tableProblem = ${JSON.stringify(sectionTableProblem(sources))};
if (__tableProblem) throw new Error(__tableProblem);
` : '';
    const wanted = sectionInputTables(sources);
    const inputTables = wanted.length > 0 ? `// The tables of the node's input this section's heatmaps and joins read, found
// in the inputs the sandbox gives the run before anything loads
// (inputTablesFrom, as the host defines it): one the input does not carry fails
// with the words the host gives it. Each is loaded just before the first entry
// that reads it, in that entry's workspace (withInputTables), and handed on only
// when a join wrote its columns onto it (handedOn).
const __inputTables = ${JSON.stringify(wanted)};
const __inputTablesFrom = ${inputTablesFrom.toString()};
const __coordinateFormatOf = ${coordinateFormatOf.toString()};
const __withInputTables = ${withInputTables.toString()};
const __handedOn = ${handedOn.toString()};
const __inputKeys = ${JSON.stringify(wanted.map((table) => autkTableKey(table.workspace, table.name)))};
const __joinRoots = ${JSON.stringify(sectionJoinRoots(sources))};
const __carried = __inputTablesFrom(typeof __inputs === 'undefined' ? {} : __inputs, __inputTables).map((table) => ({
  before: table.before,
  source: {
    type: 'geojson',
    outputTableName: table.name,
    geojsonObject: table.rows,
    coordinateFormat: __coordinateFormatOf(table.rows),
    ...(table.layerType ? { layerType: table.layerType } : {}),
    ...(table.workspace ? { workspace: table.workspace } : {}),
  },
}));
const __runs = __withInputTables(__sources, __carried);
` : '';
    const grammarAdapter = grammarSources ? `// The grammar's own data adapter, which loads a source of these types as the
// grammar does. The raster table it makes is read back at once, in the
// workspace it was built in, with the grid its cells lie on (withRasterGrid),
// in the envelope it is handed on in (rasterEnvelope), as the host defines them.
const __adapter = createDataAdapter();
const __grammarSources = ${JSON.stringify(GRAMMAR_RASTER_SOURCES)};
const __withRasterGrid = ${withRasterGrid.toString()};
const __rasterEnvelope = ${rasterEnvelope.toString()};
` : '';
    const grammarLoad = grammarSources ? `    else if (__grammarSources.includes(type)) {
      await __adapter.resolveSource(db, source);
      const __raster = await db.getRaster(rest.outputTableName);
      const __crs = db.getWorkspaceConfiguration().coordinateFormat;
      const __envelope = __rasterEnvelope(__withRasterGrid(__raster, __crs), rest.outputTableName);
      // A raster in another workspace than the default one names it, as a
      // table does, so the node it is handed to loads it there.
      if (source.workspace !== undefined) __envelope.workspace = source.workspace;
      __rasters.push(__envelope);
    }
` : '';
    return `import { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT } from '@urban-toolkit/autk-db';${dataEntryImport}
const __sources = ${JSON.stringify(sources)};
// Computed host-side by requestedLayerTables so the naming rules live in ONE
// place rather than being restated inside this emitted string.
const __expectedTables = ${JSON.stringify(requestedLayerTables(sources))};
const __loadErrors = [];
// Mirrors joinFailureMessage() host-side; see the throw after the contract check.
const __joinErrors = [];
// loadableFeatures, withOsmIds and joinQueryParams, as the host defines them
// (autkDataCompile.ts).
const __loadableFeatures = ${loadableFeatures.toString()};
const __withOsmIds = ${withOsmIds.toString()};
const __joinQueryParams = ${joinQueryParams.toString()};
${tableCheck}${inputTables}${grammarAdapter}// The raster tables the data section made, each in its envelope.
const __rasters = [];
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
for (const source of ${wanted.length > 0 ? '__runs' : '__sources'}) {
${parts.load}
    if (type === 'osm') await db.loadOsm(rest);
    else if (type === 'geojson') await db.loadGeojson(await __loadableGeojson(rest));
    else if (type === 'csv') await db.loadCsv(rest);
    else if (type === 'json') await db.loadJson(rest);
    // In-grammar spatial join between already-loaded tables (sources run in
    // spec order, so the join must come after the tables it references):
    // near: { distance } in workspace meters, groupBy as an array of column specs.
    else if (type === 'join') await db.spatialQuery(__joinQueryParams(rest));
${grammarLoad}    else console.log('[autk-grammar] unsupported data source type "' + type + '" - skipped');
  } catch (e) {
    // Recorded, not discarded: this reason is the only account of WHY a layer is
    // missing, and the contract check below attaches it to the thrown error.
    __loadErrors.push(type + ': ' + ((e && e.message) || String(e)));
    if (type === 'join') __joinErrors.push((e && e.message) || String(e));
    console.log('[autk-grammar] data load failed for source type "' + type + '": ' + (e && e.message));
  }
}
${parts.readBack}
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
${parts.each}
${wanted.length > 0 ? `${parts.skip}\n` : ''}  const geojson = await db.getLayer(t.name);
  let type = t.type ?? 'polygons';
  // Each OpenStreetMap feature's OSM id in osm_id, a building part's in that part.
  if (geojson && Array.isArray(geojson.features)) geojson.features = __withOsmIds(t, geojson.features);
  if (type === 'buildings' && Array.isArray(geojson?.features)) {
    // autk-db keeps a building as one GeometryCollection, each part's tags in
    // properties.parts naming its geometry by geometryIndex. Explode each building
    // into one footprint feature per part, carrying that part's tags and height, as
    // explodeBuildingParts does in the browser (autkLayerMaterialize.ts). The
    // downstream loadGeojson('buildings') makes every row a building of its own, so
    // each part also carries, as a property, the building_id it came from. A part's
    // geometryIndex is autk-db's bookkeeping and is left out, and so is its id,
    // which the part carries as its osm_id.
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
${parts.handOn}
}
for (const __raster of __rasters) __out.push(__raster);
return __out;`;
}
