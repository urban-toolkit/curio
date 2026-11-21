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

// Where each source of a data section runs. autk-grammar runs a source with
// `after: 'compute'` once every compute pass has run, in the order of `data`,
// after every source without it, wherever it stands in `data`; its own
// `dataPhases` splits a document so, and refuses an `after` other than
// 'compute' and a source after compute that reads a table a pass writes
// without `writeBack`. The node calls it where it has the grammar at hand (its
// run in the browser, the sandbox's code); here, without the grammar, the
// order alone. A node loads the sources before compute where it loads its data
// section (the sandbox, or the browser's loader), and runs those after compute
// in the browser once its passes have run. A document with no compute pass has
// nothing for them to wait for: they load with the others, after them.

// Whether a source of *dataSources* writes `after`, the key that moves it
// after the compute passes.
export function writesAfter(dataSources: unknown): boolean {
    return Array.isArray(dataSources)
        && dataSources.some((source) => source != null && typeof source === 'object' && source.after !== undefined);
}

// *dataSources* in the order autk-grammar runs them when no pass runs between
// them: those without `after`, then those with it, each in the order of `data`.
export function inPhaseOrder(dataSources: any[]): any[] {
    const sources: any[] = Array.isArray(dataSources) ? dataSources : [];
    if (!writesAfter(sources)) return sources;
    return [
        ...sources.filter((source) => source == null || source.after === undefined),
        ...sources.filter((source) => source != null && source.after !== undefined),
    ];
}

// Whether *spec* has compute passes, which its sources after compute wait for.
function hasPasses(spec: any): boolean {
    return spec != null && Array.isArray(spec.compute) && spec.compute.length > 0;
}

// The sources a node loads where it loads a document's data section: those
// before compute, then, when the document has no compute pass, those after
// compute (inPhaseOrder).
export function loadedSources(spec: any): any[] {
    const sources: any[] = spec != null && Array.isArray(spec.data) ? spec.data : [];
    if (!writesAfter(sources)) return sources;
    return hasPasses(spec) ? sources.filter((source) => source == null || source.after === undefined) : inPhaseOrder(sources);
}

// The sources a node runs in the browser once its compute passes have run:
// those after compute, in the order of `data`, of a document that has passes.
export function sourcesAfterPasses(spec: any): any[] {
    const sources: any[] = spec != null && Array.isArray(spec.data) ? spec.data : [];
    return hasPasses(spec) ? sources.filter((source) => source != null && source.after !== undefined) : [];
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

// The source types that make a raster table: a heatmap, which autk-db's
// `buildHeatmap` builds, and a GeoTIFF, which its `loadGeoTiff` reads. Both
// loaders hand every source to autk-grammar's own data adapter
// (`createDataAdapter().resolveSource`, from the grammar's `./data` entry,
// which imports autk-db alone), and read a raster table back at once, with
// the grid its cells lie on (withRasterGrid), to hand it on as Curio hands on
// a raster (rasterEnvelope). contracts/autkGrammar.json holds this list too,
// as `rasterSources`.
export const GRAMMAR_RASTER_SOURCES = ['heatmap', 'geotiff'];

// The source types that make a table of their own `outputTableName`, an
// OpenStreetMap area's aside: a CSV, JSON or GeoJSON table, a raster, and a
// SQL query's table. A join, an update and a drop make none: they change or
// drop a table another source made.
const TABLE_SOURCES = ['geojson', 'csv', 'json', 'sql', ...GRAMMAR_RASTER_SOURCES];

// The tables an OpenStreetMap area loads: one per layer of its
// `autoLoadLayers`, `<outputTableName>_<layer>`, and one per tag set,
// `<outputTableName>_<name>_<type>`, each named as autk-db names it.
function osmTables(source: any): string[] {
    const out = source?.outputTableName;
    if (typeof out !== 'string' || out === '') return [];
    const layers: any[] = Array.isArray(source?.autoLoadLayers?.layers) ? source.autoLoadLayers.layers : [];
    const tagSets: any[] = Array.isArray(source?.tagSets) ? source.tagSets : [];
    return [
        ...layers.map((layer) => `${out}_${layer}`),
        ...tagSets.filter((set) => set?.name && set?.type).map((set) => `${out}_${set.name}_${set.type}`),
    ];
}

// The keys of the OpenStreetMap tables a document's own data section loads
// (osmTables) that its maps' layers and its plots read as OpenStreetMap
// elements (`osmElements`), each in the view's workspace: both loaders read
// each as one feature per element, which the views then draw. A table of the
// node's input is no OpenStreetMap table of its database, so a view reads it
// row by row, as autk-grammar reads any other table. So is a table a GPGPU or
// clusters pass changes in place and keeps in autk-db (`writeBack`):
// autk-grammar then reads it row by row, the pass's rows. (A view of one a
// pass changes in place without `writeBack` is refused:
// contracts/autkGrammar autkOsmElementsProblem.)
export function osmElementTables(spec: any): string[] {
    const list = (held: any): any[] => (held == null ? [] : Array.isArray(held) ? held : [held]);
    const own = new Set(list(spec?.data)
        .filter((source) => source?.type === 'osm')
        .flatMap((source) => osmTables(source).map((table) => autkTableKey(autkWorkspaceOf(source), table))));
    const writtenBack = new Set(list(spec?.compute)
        .filter((pass) => (pass?.type == null || pass.type === 'gpgpu' || pass.type === 'clusters')
            && !(typeof pass?.outputTableName === 'string' && pass.outputTableName !== '')
            && Boolean(pass?.writeBack) && typeof pass?.dataRef === 'string')
        .map((pass) => autkTableKey(autkWorkspaceOf(pass), pass.dataRef)));
    const keys: string[] = [];
    const read = (view: any, table: unknown) => {
        if (typeof table !== 'string' || table === '') return;
        const key = autkTableKey(autkWorkspaceOf(view), table);
        if (own.has(key) && !writtenBack.has(key) && !keys.includes(key)) keys.push(key);
    };
    for (const map of list(spec?.map)) {
        for (const layer of list(map?.layerRefs)) if (layer?.osmElements === true) read(map, layer.dataRef);
    }
    for (const plot of list(spec?.plot)) if (plot?.osmElements === true) read(plot, plot.dataRef);
    return keys;
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
// Naming mirrors autk-db's own: an OpenStreetMap area's layers and tag sets
// (osmTables), and any other source's `outputTableName`, a SQL query's
// included. Each table is named by its key (autkTableKey), in the workspace
// its source loads it into, once, in the order its sources make them. A
// heatmap's or a GeoTIFF's raster table is one of them: the loaders read it
// back by its key. A table a later `drop` drops is no longer asked for, until
// a source after it makes one of that name again. The sources are read in the
// order autk-grammar runs them (inPhaseOrder), so a drop after compute drops
// the table a source before compute made, wherever each stands in `data`.
export function requestedLayerTables(dataSources: any[]): string[] {
    const names: string[] = [];
    const add = (key: string) => {
        if (!names.includes(key)) names.push(key);
    };
    for (const source of inPhaseOrder(dataSources ?? [])) {
        const { type, ...rest } = (source ?? {}) as any;
        const workspace = autkWorkspaceOf(rest);
        if (type === 'osm') {
            // Per-layer and per-tag-set tables only: autk-db drops the raw OSM
            // import tables once it has extracted them.
            for (const table of osmTables(rest)) add(autkTableKey(workspace, table));
        } else if (TABLE_SOURCES.includes(type)) {
            if (rest?.outputTableName) add(autkTableKey(workspace, rest.outputTableName));
        } else if (type === 'drop' && typeof rest?.dataRef === 'string') {
            const at = names.indexOf(autkTableKey(workspace, rest.dataRef));
            if (at >= 0) names.splice(at, 1);
        }
        // A join and an update are skipped on purpose: each rewrites a table
        // another source already created rather than adding a layer of its
        // own, so expecting one would report a phantom miss.
    }
    return names;
}

// A table a data section's heatmap, join, update or drop reads: its name, the
// workspace of the entry that reads it, its key there (autkTableKey), the
// entry's place in the section, and the words that name the entry when the
// table is missing. A heatmap bins its `joinDataRef`; a join reads its
// `dataRef`, the table that receives the joined columns, and its
// `joinDataRef`, the table joined onto it; an update changes the rows of its
// `dataRef`, and a drop drops it.
type SectionRead = { at: number; name: string; workspace?: string; key: string; reader: string };

// The tables a data source reads by name, in its own workspace, as sectionReads
// finds them: a heatmap's `joinDataRef`, a join's `dataRef` and `joinDataRef`,
// and an update's or a drop's `dataRef`. A SQL query is not read for its tables.
export function tablesReadBy(source: any): string[] {
    const named = (table: unknown): table is string => typeof table === 'string' && table !== '';
    if (source?.type === 'heatmap') return [source.joinDataRef].filter(named);
    if (source?.type === 'join') return [source.dataRef, source.joinDataRef].filter(named);
    if (source?.type === 'update' || source?.type === 'drop') return [source.dataRef].filter(named);
    return [];
}

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
        } else if (source?.type === 'update' && named(source.dataRef)) {
            read(source.dataRef, 'The update changes');
        } else if (source?.type === 'drop' && named(source.dataRef)) {
            read(source.dataRef, 'The drop drops');
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

// The keys of a data section's own tables: those its sources load and make
// (requestedLayerTables), and every name a source of it gives its table
// (`outputTableName`, an OSM load's and a SQL query's included), dropped or
// not. Any other table a source of it reads is one of the node's input.
export function sectionOwnTables(dataSources: any[]): Set<string> {
    const sources: any[] = Array.isArray(dataSources) ? dataSources : [];
    return new Set([
        ...requestedLayerTables(sources),
        ...sources
            .filter((source) => typeof source?.outputTableName === 'string' && source.outputTableName !== '')
            .map((source) => autkTableKey(autkWorkspaceOf(source), source.outputTableName)),
    ]);
}

// A table of the node's input that a data section's heatmap or join reads: its
// name and the workspace of the entry that reads it first, `before`, that
// entry's place, where both loaders load it into the section's database, and
// what the load fails with when the input does not carry it.
export type SectionInputTable = { name: string; workspace?: string; before: number; missing: string };

// The tables a data section's heatmaps, joins, updates and drops read that
// none of its own sources loads, which the node's input carries, each once, by
// key, in the order the section first reads them. A section's own are the
// tables its sources load and make (requestedLayerTables) and every name a
// source of it gives its table (`outputTableName`, an OSM load's and a SQL
// query's included). The input names them as the node reads its input
// everywhere (utils/autkInput autkSourcesFrom): `input_<k>` for what arrives
// on circle k, a layer by its own name. A section that reads none of them
// reads no input. The section is read in the order autk-grammar runs it
// (inPhaseOrder), and `before` is a place in that order, the order both
// loaders load it in.
export function sectionInputTables(dataSources: any[]): SectionInputTable[] {
    const sources: any[] = inPhaseOrder(Array.isArray(dataSources) ? dataSources : []);
    const loaded = sectionOwnTables(sources);
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

// The keys of the tables a data section's joins write their columns onto and
// its updates change (their `dataRef`): an input table one of them names is
// what the join or the update made of it, so the section hands it on
// (handedOn).
export function sectionChangedTables(dataSources: any[]): string[] {
    const sources: any[] = Array.isArray(dataSources) ? dataSources : [];
    return Array.from(new Set(sources
        .filter((source) => (source?.type === 'join' || source?.type === 'update')
            && typeof source.dataRef === 'string' && source.dataRef !== '')
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
// each table of the input a join of it wrote its columns onto or an update of
// it changed (handedOn).
export function sectionTablesHandedOn(dataSources: any[]): string[] {
    const sources: any[] = Array.isArray(dataSources) ? dataSources : [];
    const changed = sectionChangedTables(sources);
    const fromInput = sectionInputTables(sources)
        .map((table) => autkTableKey(table.workspace, table.name))
        .filter((key) => changed.includes(key));
    return [...requestedLayerTables(sources), ...fromInput];
}

// Whether a data section hands on the table of *key*: every table it loads and
// makes, but an input table it loaded (*inputKeys*), which the node's input
// already brings, unless a join wrote its columns onto it or an update changed
// it (*changed*). Both loaders go through this one function
// (compileDataSpecToAutkDbJs embeds its source), so the body avoids what
// loadableFeatures avoids.
export function handedOn(key: string, inputKeys: string[], changed: string[]): boolean {
    return inputKeys.indexOf(key) < 0 || changed.indexOf(key) >= 0;
}

// A table's rows as Curio hands them to autk-db, which refuses a row whose
// geometry is missing and reads a layer's kind off its first row. A row with no
// geometry gets an empty one, a GeometryCollection with none in it: it loads,
// a map draws nothing for it and a plot still counts it. When the first row has
// no geometry, it trades places with the first row that has one; `order` then
// lists, for each row handed on, the row it was (null when no row moved).
// A node's inputs go through this function (`loadableSource`); a data
// section's GeoJSON sources go through autk-grammar's own data adapter, whose
// rule is this one, each row also given the feature id autk-db gives it. So
// that the sandbox's code can embed a function of this module as it is, the
// body avoids syntax the build compiles to a shared helper (spread,
// destructuring, for...of, optional chaining).
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

// A layer's features with OpenStreetMap's numeric building tags as numbers.
// autk-db keeps every tag as text ("65.5", "86 m"); each value of these keys
// becomes a number, or null when it holds none that can be read:
// - lengths, in metres: `height`, `min_height`, `building:height` and
//   `roof:height`. A plain number is that number. A number followed by its
//   unit is converted, as OpenStreetMap writes a length (metres when no unit
//   is written): `m`, `metre`, `metres`, `meter`, `meters`, `km`, `mi`, `nmi`
//   and `ft`, in any case, and feet and inches (`282'`, `16'6"`, `6"`). A
//   length in another unit than metres is rounded to the centimetre;
// - levels, which take a plain number only: `building:levels`,
//   `building:min_level`, `levels`, `min_level`, `roof:levels` and
//   `building:levels:underground`.
// A plain number is written as the expression language writes one, signed,
// with nothing around it once trimmed (NUMBER_TEXT in
// utils/editFeatures/applyEdits.ts). Any other text ("tall", "~20", "7-7",
// "4.0;11.6") is null, so a building with no height that can be read takes
// the default height where a height is used (utils/buildingHeight). A number
// stays the number it is, and a key a feature does not have stays missing. A
// building's own tags and each part's in `properties.parts` are read alike.
// These keys are the heights and levels among the Discovery Catalog's numeric
// tags (discovery/domain/osm_values.py). The surface, a raster and a layer
// from another source come back as they are; the input is never changed.
// Both loaders hand their layers on through this one function, after
// withOsmIds, and so does a compute step that reads a table back from its
// database (autkComputeDatabase); the sandbox's code embeds its source, so the
// body avoids what withOsmIds avoids.
export function withOsmNumbers(table: { source?: string; type?: string } | null | undefined, features: any[]): any[] {
    if (table == null || table.source !== 'osm' || table.type === 'surface' || table.type === 'raster'
        || !Array.isArray(features)) return features;
    const lengths = ['height', 'min_height', 'building:height', 'roof:height'];
    const levels = ['building:levels', 'building:min_level', 'levels', 'min_level', 'roof:levels', 'building:levels:underground'];
    const keys = lengths.concat(levels);
    const number = '[+-]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)(?:[eE][+-]?[0-9]+)?';
    const plain = new RegExp('^' + number + '$');
    const withUnit = new RegExp('^(' + number + ')\\s*(m|metres?|meters?|km|mi|nmi|ft)$', 'i');
    const feetAndInches = /^(?:([0-9]+(?:\.[0-9]+)?)\s*')?\s*(?:([0-9]+(?:\.[0-9]+)?)\s*")?$/;
    const metresIn: Record<string, number> = {
        m: 1, metre: 1, metres: 1, meter: 1, meters: 1, km: 1000, mi: 1609.344, nmi: 1852, ft: 0.3048,
    };
    const finite = function (value: number) { return Number.isFinite(value) ? value : null; };
    const centimetres = function (value: number) { return finite(Math.round(value * 100) / 100); };
    const read = function (key: string, value: any): any {
        if (value === null || value === undefined) return value;
        if (typeof value === 'number') return finite(value);
        if (typeof value !== 'string') return null;
        const text = value.trim();
        if (plain.test(text)) return finite(Number(text));
        if (levels.indexOf(key) >= 0) return null;
        const unit = withUnit.exec(text);
        if (unit !== null) {
            const factor = metresIn[unit[2].toLowerCase()];
            return factor === 1 ? finite(Number(unit[1])) : centimetres(Number(unit[1]) * factor);
        }
        const imperial = feetAndInches.exec(text);
        if (imperial !== null && (imperial[1] !== undefined || imperial[2] !== undefined)) {
            return centimetres(Number(imperial[1] || 0) * 0.3048 + Number(imperial[2] || 0) * 0.0254);
        }
        return null;
    };
    const numbered = function (properties: any): any {
        if (properties == null || Object.prototype.toString.call(properties) !== '[object Object]') return properties;
        let out = properties;
        for (let i = 0; i < keys.length; i++) {
            const key = keys[i];
            if (!Object.prototype.hasOwnProperty.call(properties, key)) continue;
            const value = read(key, properties[key]);
            if (value === properties[key]) continue;
            if (out === properties) out = Object.assign({}, properties);
            out[key] = value;
        }
        return out;
    };
    return features.map(function (feature: any) {
        if (feature == null) return feature;
        const properties = numbered(feature.properties);
        const given = properties != null && Array.isArray(properties.parts) ? properties.parts : [];
        const parts = given.map(numbered);
        const partsChanged = parts.some(function (part: any, at: number) { return part !== given[at]; });
        if (properties === feature.properties && !partsChanged) return feature;
        const next = partsChanged ? Object.assign({}, properties, { parts: parts }) : properties;
        return Object.assign({}, feature, { properties: next });
    });
}

// The number withOsmNumbers makes of the value *value* of the tag *key* of an
// OpenStreetMap feature: a number, null, or, for a key it does not read, the
// value as it is.
export function osmNumber(key: string, value: any): any {
    const out = withOsmNumbers({ source: 'osm', type: 'buildings' }, [{ properties: { [key]: value } }]);
    return out[0].properties[key];
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
// besides its data adapter (`enterWorkspace` and `tableKey`), each workspace's
// tables read back in turn, with the raster tables it made, and each table
// handed on with its workspace. A data section that names none compiles
// without them: its tables are all in the default workspace.
function workspaceCode(uses: boolean) {
    if (!uses) {
        return {
            fromDataEntry: [] as string[],
            skip: '  if (!__handedOn(t.name, __inputKeys, __changed)) continue;',
            readBack: `let __tables = [];
try {
  __tables = db.getLayersMetadata();
} catch (e) {
  // A partially-loaded DB can throw here rather than return [] - treat it as
  // "no usable tables" and let the contract check report it.
  __loadErrors.push('getLayersMetadata: ' + ((e && e.message) || String(e)));
}
const __have = new Set(__tables.map((t) => t.name).concat(__rasters.map((r) => r.layerName)));`,
            each: 'for (const t of __tables) {\n  const workspace = undefined;',
            handOn: '  __out.push({ name: t.name, type, geojson });',
        };
    }
    return {
        fromDataEntry: ['enterWorkspace', 'tableKey'],
        skip: '  if (!__handedOn(tableKey(workspace, t.name), __inputKeys, __changed)) continue;',
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

// The CRS of each workspace a document's `workspaces` sets, by its name, ''
// for the default one: the CRS a table of that workspace is handed on in,
// autk-db's DEFAULT_WORKSPACE_COORDINATE_FORMAT for any other. A workspace
// written as the default's name is the default one.
export function workspaceCrsOf(workspaces: unknown): Record<string, string> {
    const crs: Record<string, string> = {};
    for (const entry of Array.isArray(workspaces) ? workspaces : []) {
        const format = (entry as any)?.coordinateFormat;
        if (typeof format !== 'string' || format === '') continue;
        crs[autkWorkspaceOf({ workspace: (entry as any)?.name }) ?? ''] = format;
    }
    return crs;
}

// The EPSG code a table read back from autk-db is handed on in: 4326 when its
// first coordinates read as degrees (a table autk-db was handed in degrees and
// kept so), else its workspace's CRS (*crsOf*, workspaceCrsOf) or autk-db's
// default (*fallback*). A wrong one silently breaks the next node, whose map
// reads degrees as metres near the origin and shows a blank view. Both loaders
// go through this one function (compileDataSpecToAutkDbJs embeds its source),
// so the body avoids what loadableFeatures avoids.
export function layerEpsg(geojson: any, workspace: string | undefined, crsOf: Record<string, string>, fallback: string): string {
    const code = function (format: string) {
        const found = String(format).match(/(\d+)/);
        return found ? found[1] : '3395';
    };
    const features = (geojson && geojson.features) || [];
    for (let i = 0; i < Math.min(features.length, 5); i++) {
        let c = features[i] && features[i].geometry && features[i].geometry.coordinates;
        while (Array.isArray(c) && Array.isArray(c[0])) c = c[0];
        if (Array.isArray(c) && Number.isFinite(c[0]) && Number.isFinite(c[1])) {
            if (Math.abs(c[0]) <= 180 && Math.abs(c[1]) <= 90) return '4326';
            break;
        }
    }
    const own = crsOf[workspace === undefined ? '' : workspace];
    return code(own !== undefined ? own : fallback);
}

// The source types whose table can have no geometry, which autk-db lists as no
// layer: a CSV or a JSON table loaded without geometry columns, and a SQL
// query's table saved without a `layerType`.
export const PLAIN_TABLE_SOURCES = ['csv', 'json', 'sql'];

// A table a data section's own CSV, JSON or SQL source made with no geometry,
// which autk-db lists as no layer, as both loaders hand it on: its rows, each a
// feature with no geometry and the row as its properties, as autk-grammar reads
// such a table for a plot, under its name and with no layer type, in its
// workspace when that is another than the default one. Both loaders go through
// this one function (compileDataSpecToAutkDbJs embeds its source), so the body
// avoids what loadableFeatures avoids.
export function plainTableRecord(name: string, rows: any[], workspace?: string): any {
    const geojson = {
        type: 'FeatureCollection',
        features: rows.map(function (properties: any) {
            return { type: 'Feature', geometry: null, properties: properties };
        }),
    };
    return workspace === undefined ? { name: name, geojson: geojson } : { name: name, geojson: geojson, workspace: workspace };
}

// The sandbox's code that reads back the tables of the section's own CSV, JSON
// and SQL sources that autk-db made with no geometry, each once, in its
// source's workspace (`enterWorkspace` when the section names one), as the
// load left it (an update's rows among them), and counts each as a table the
// load made (`__have`), then hands them on after the layers, in their sources'
// order (plainTableRecord). A table a drop dropped is gone. The browser's
// loader reads them the same way (autkLayerMaterialize's plainTables). A
// section with no such source compiles without it.
function plainTablesCode(sources: any[], usesWorkspaces: boolean) {
    if (!sources.some((source) => PLAIN_TABLE_SOURCES.includes(source?.type))) return { readBack: '', handOn: '' };
    const enter = usesWorkspaces ? '\n    await enterWorkspace(db, workspace);' : '';
    const key = usesWorkspaces ? 'tableKey(__plain.workspace, __plain.name)' : '__plain.name';
    const read = usesWorkspaces ? 'tableKey(workspace, outputTableName)' : 'outputTableName';
    return {
        readBack: `
// The tables of the section's own CSV, JSON and SQL sources that autk-db made
// with no geometry: autk-db lists none of them among its layers, which are read
// already.
const __plainTableRecord = ${plainTableRecord.toString()};
const __plainSources = ${JSON.stringify(PLAIN_TABLE_SOURCES)};
const __plainTables = [];
for (const source of __sources) {
  const { type, workspace, outputTableName } = source ?? {};
  if (!__plainSources.includes(type) || !outputTableName || __have.has(${read})) continue;
  try {${enter}
    const table = db.getTablesMetadata().find((t) => t.name === outputTableName);
    if (!table || table.type !== undefined) continue;
    __plainTables.push(__plainTableRecord(outputTableName, await db.getTable(outputTableName), workspace));
  } catch (e) {
    __loadErrors.push(type + ': ' + ((e && e.message) || String(e)));
  }
}
for (const __plain of __plainTables) __have.add(${key});`,
        handOn: '// Each table with no geometry, as its rows.\nfor (const __plain of __plainTables) __out.push(__plain);\n',
    };
}

// Compile a grammar `data` section into autk-db JavaScript to run in the backend
// Node.js sandbox. The top-level `import` is rewritten to `await import()` by
// execute_js_code, and so is autk-grammar's data entry's, the one line that
// imports what the section needs of it: its data adapter (`createDataAdapter`),
// and `enterWorkspace` and `tableKey` for a section that names a workspace.
// The rest is the body of the async function the sandbox wraps user code in.
// Mirrors loadSpecLayers exactly, with the spec inlined as a literal and
// flattenToMultiPolygon inlined (the module-level helper above is not in the
// sandbox's scope). The document's `workspaces` (*options.workspaces*) are set
// up first, and every source is loaded as autk-grammar's run loads one,
// through the grammar's own data adapter (`resolveSource`), which enters the
// source's workspace and leaves it current. A heatmap's or a GeoTIFF's raster
// table is read back at once. A section whose heatmaps, joins, updates or
// drops read tables of the node's input (sectionInputTables) finds them in
// the inputs the sandbox gives the run, `__inputs` (sandbox/util/js_wrapper.mjs),
// which the node's run in the browser and a run on the server both send, and
// loads each just before the first entry that reads it; one that reads none
// compiles without them. An OpenStreetMap table a view of the node reads with
// `osmElements` (*options.elements*, by key) is read as one feature per
// OpenStreetMap element. The sources load in the order autk-grammar runs them
// (inPhaseOrder): a section with sources after compute, which is a section of
// no compute pass, loads them after the others, and its code first asks the
// grammar's own `dataPhases` of the section, which refuses an `after` other
// than 'compute' before anything loads. The function returns Array<{name, type, geojson}>,
// each table in the CRS of its workspace, each raster table after them in its
// envelope (rasterEnvelope), each table or raster in another workspace than
// the default one with its `workspace` too, which the sandbox persists to
// DuckDB.
export function compileDataSpecToAutkDbJs(
    dataSources: any[],
    options: { workspaces?: unknown; elements?: string[] } = {},
): string {
    const sources = inPhaseOrder(dataSources ?? []).map(inItsWorkspace);
    const usesWorkspaces = autkUsesWorkspaces({ data: sources });
    const parts = workspaceCode(usesWorkspaces);
    const workspaces = Array.isArray(options.workspaces) && options.workspaces.length > 0 ? options.workspaces : null;
    const phased = writesAfter(sources);
    const fromDataEntry = ['createDataAdapter', ...(phased ? ['dataPhases'] : []), ...parts.fromDataEntry];
    const phaseCheck = phased ? `// The grammar's own phases of the section, which refuse an \`after\` other than
// 'compute' before anything loads. The section has no compute pass, so its
// sources after compute load after the others, as __sources holds them.
dataPhases({ data: __sources });
` : '';
    const tableCheck = sectionReads(sources).length > 0 ? `// A heatmap, a join, an update or a drop that reads a table this section
// loads only after it fails before anything loads, with the words the host
// gives it (sectionTableProblem).
const __tableProblem = ${JSON.stringify(sectionTableProblem(sources))};
if (__tableProblem) throw new Error(__tableProblem);
` : '';
    const wanted = sectionInputTables(sources);
    const inputTables = wanted.length > 0 ? `// The tables of the node's input this section's heatmaps, joins, updates and
// drops read, found in the inputs the sandbox gives the run before anything
// loads (inputTablesFrom, as the host defines it): one the input does not
// carry fails with the words the host gives it. Each is loaded just before the
// first entry that reads it, in that entry's workspace (withInputTables), and
// handed on only when a join wrote its columns onto it or an update changed it
// (handedOn).
const __inputTables = ${JSON.stringify(wanted)};
const __inputTablesFrom = ${inputTablesFrom.toString()};
const __coordinateFormatOf = ${coordinateFormatOf.toString()};
const __withInputTables = ${withInputTables.toString()};
const __inputKeys = ${JSON.stringify(wanted.map((table) => autkTableKey(table.workspace, table.name)))};
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
    const handOnCheck = wanted.length > 0 ? `const __handedOn = ${handedOn.toString()};
const __changed = ${JSON.stringify(sectionChangedTables(sources))};
` : '';
    const plain = plainTablesCode(sources, usesWorkspaces);
    const keyOf = usesWorkspaces ? 'tableKey(workspace, t.name)' : 't.name';
    // The code's second import, the grammar's data entry's, written as a
    // string so no line of this module starts an import of its own.
    const dataEntryImport = `\nimport { ${fromDataEntry.join(', ')} } from '@urban-toolkit/autk-grammar/data';`;
    return `import { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT } from '@urban-toolkit/autk-db';${dataEntryImport}
const __sources = ${JSON.stringify(sources)};
// The document's workspaces, set up before the first source loads, and the CRS
// of each, which its tables are handed on in (workspaceCrsOf).
const __workspaceSetup = ${JSON.stringify(workspaces)};
const __crsOf = ${JSON.stringify(workspaceCrsOf(workspaces))};
// The OpenStreetMap tables a view of the node reads as OpenStreetMap elements, by key.
const __elements = ${JSON.stringify(options.elements ?? [])};
// Computed host-side by requestedLayerTables so the naming rules live in ONE
// place rather than being restated inside this emitted string.
const __expectedTables = ${JSON.stringify(requestedLayerTables(sources))};
const __loadErrors = [];
// The failures of the sources that change a table another source made (a join,
// an update, a drop), which leave no table missing; see the throw after the
// contract check.
const __changeErrors = [];
const __joinErrors = [];
// withOsmIds, withOsmNumbers and layerEpsg, as the host defines them (autkDataCompile.ts).
const __withOsmIds = ${withOsmIds.toString()};
const __withOsmNumbers = ${withOsmNumbers.toString()};
const __layerEpsg = ${layerEpsg.toString()};
${phaseCheck}${tableCheck}${inputTables}${handOnCheck}// autk-grammar's own data adapter, which loads every source as the grammar's run
// loads one. A raster table it makes is read back at once, in the workspace it
// was built in, with the grid its cells lie on (withRasterGrid), in the
// envelope it is handed on in (rasterEnvelope), as the host defines them.
const __adapter = createDataAdapter();
const __grammarSources = ${JSON.stringify(GRAMMAR_RASTER_SOURCES)};
const __changingSources = ['join', 'update', 'drop'];
const __withRasterGrid = ${withRasterGrid.toString()};
const __rasterEnvelope = ${rasterEnvelope.toString()};
// The raster tables the data section made, each in its envelope.
const __rasters = [];
const db = new AutkDb();
await db.init();
// A workspace autk-db refuses fails the load before any source loads.
if (__workspaceSetup) await __adapter.resolveWorkspaces(db, __workspaceSetup);
for (const source of ${wanted.length > 0 ? '__runs' : '__sources'}) {
  const { type, ...rest } = source ?? {};
  try {
    await __adapter.resolveSource(db, source);
    if (__grammarSources.includes(type)) {
      const __raster = await db.getRaster(rest.outputTableName);
      const __crs = db.getWorkspaceConfiguration().coordinateFormat;
      const __envelope = __rasterEnvelope(__withRasterGrid(__raster, __crs), rest.outputTableName);
      // A raster in another workspace than the default one names it, as a
      // table does, so the node it is handed to loads it there.
      if (source.workspace !== undefined) __envelope.workspace = source.workspace;
      __rasters.push(__envelope);
    }
  } catch (e) {
    // Recorded, not discarded: this reason is the only account of WHY a layer is
    // missing, and the contract check below attaches it to the thrown error.
    __loadErrors.push(type + ': ' + ((e && e.message) || String(e)));
    if (type === 'join') __joinErrors.push((e && e.message) || String(e));
    else if (__changingSources.includes(type)) __changeErrors.push((e && e.message) || String(e));
    console.log('[autk-grammar] data load failed for source type "' + type + '": ' + (e && e.message));
  }
}
${parts.readBack}${plain.readBack}
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
if (__changeErrors.length > 0) {
  // So does an update or a drop: it fails in the grammar's words.
  throw new Error(__changeErrors.join('; '));
}
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
const __out = [];
${parts.each}
${wanted.length > 0 ? `${parts.skip}\n` : ''}  // An OpenStreetMap table a view reads as elements: one feature per element.
  const geojson = __elements.includes(${keyOf}) ? await db.getLayer(t.name, { osmElements: true }) : await db.getLayer(t.name);
  let type = t.type ?? 'polygons';
  // Each OpenStreetMap feature's OSM id in osm_id, a building part's in that
  // part, and its numeric building tags as numbers.
  if (geojson && Array.isArray(geojson.features)) geojson.features = __withOsmNumbers(t, __withOsmIds(t, geojson.features));
  if (type === 'buildings' && Array.isArray(geojson?.features)) {
    // autk-db keeps a building as one GeometryCollection, each part's tags in
    // properties.parts naming its geometry by geometryIndex. Explode each building
    // into one footprint feature per part, carrying that part's tags, as
    // explodeBuildingParts does in the browser (autkLayerMaterialize.ts): a part
    // with no height is handed on with none. The downstream
    // loadGeojson('buildings') makes every row a building of its own, so each part
    // also carries, as a property, the building_id it came from. A part's
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
  // Each table says the CRS its coordinates are in: its workspace's, or degrees
  // for one autk-db was handed in degrees and kept so (layerEpsg).
  if (geojson && typeof geojson === 'object') {
    geojson.crs = { type: 'name', properties: { name: 'urn:ogc:def:crs:EPSG::'
      + __layerEpsg(geojson, workspace, __crsOf, DEFAULT_WORKSPACE_COORDINATE_FORMAT) } };
  }
${parts.handOn}
}
${plain.handOn}for (const __raster of __rasters) __out.push(__raster);
return __out;`;
}
