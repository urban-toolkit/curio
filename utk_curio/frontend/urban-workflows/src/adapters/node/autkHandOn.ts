/**
 * What an Autark node hands the nodes below it: by one rule for every kind of
 * node, the rule a compute step follows. In order:
 *
 * 1. its input's tables, when it has no data section of its own, or when a
 *    view or a pass names a table only its input brings (`handsOnItsInput`),
 *    each as it came or as a pass changed it, and a raster in the element it
 *    came in (`inputTablesOf`);
 * 2. each table its data section loads or makes, an input table a join or an
 *    update of the section changed among them, which the input's copy gives
 *    way to (`heldTables`). An input table the section only reads is not
 *    among them: both loaders leave it out (autkDataCompile `handedOn`);
 * 3. each table a pass writes under a name of its own. A pass that writes in
 *    place leaves its result where that table already stands;
 * 4. each table a source after compute makes, a table one of them drops gone.
 *
 * The tables a node holds are its own copies: its input as it read it, and
 * its data section's tables as its load handed them back, never as autk-db
 * exports them again. A table with no rows is not handed on, but for a raster,
 * whose cells are its rows (`withRows`).
 *
 * A table a pass wrote is that pass's result, as the node's run computed it:
 * no pass runs again to hand it on. It is copied before anything of it changes,
 * since the views of a node that draws read the same object. The columns its
 * passes computed are lifted to the top of each feature (`withLiftedColumns`),
 * in a table a source after compute wrote too, which is read back from the
 * run's database as it then stands.
 * It says the CRS its coordinates are in: the one of the table it was computed
 * from, for a compute step with no database, else its workspace's. It is a
 * table of its pass's `layerType`, else of `points` for windows, else of the
 * type of the table it was computed from (utils/autkInput `writtenTables`).
 * Where it holds the rows of a buildings table the node held, each building
 * holds the height it held again (the caller's `heights`).
 *
 * A node whose document only draws its input (utils/autkSpecKind
 * `autkOnlyDrawsItsInput`) hands on its input as it came, and a data node the
 * tables its load makes (autkDataCompile `sectionTablesHandedOn`): neither
 * assembles a hand-on here.
 *
 * The compute step's two paths (autkComputeBlocks, autkComputeDatabase) and a
 * node that draws (autkGrammarBehavior) read their passes' results and the
 * tables their sources after compute made each from where their run keeps
 * them, and hand the rest to `handOnTables`; `handOnOutput` says what goes to
 * the nodes below.
 */
import { INPUT_ROW, autkNeedsInput, withHeightsAsHeld, writtenTables, type PreparedAutkInput } from '../../utils/autkInput';
import { rasterAsItCame } from '../../utils/grammarInput';
import {
    GRAMMAR_RASTER_SOURCES,
    autkTableKey,
    autkWorkspaceOf,
    layerEpsg,
    loadedSources,
    plainTableRecord,
    requestedLayerTables,
    sectionChangedTables,
    withOsmIds,
    withOsmNumbers,
    withRasterGrid,
} from './autkDataCompile';
import { RASTER_TABLE, explodeBuildingParts, toPoolOutput, type AutkLayer, type StoredHandOn } from './autkLayerMaterialize';
import { hasFeatures } from './autkRunDescriptions';
import type { JavaScriptInterpreter } from '../../JavaScriptInterpreter';

/** A table an Autark node hands on: its name, its type, its rows, its workspace (autkLayerMaterialize `AutkLayer`). */
export type HandOnTable = AutkLayer;
export type { StoredHandOn } from './autkLayerMaterialize';

/** A table's key: its name in the default workspace, `<workspace>/<name>` in another. */
const keyOf = (table: { name: string; workspace?: string }): string => autkTableKey(table.workspace, table.name);

/**
 * Whether a node hands on its input's tables: when it has no data section of
 * its own, or when a view or a pass names a table only its input brings
 * (utils/autkInput `autkNeedsInput`). The compute step's own test, which every
 * kind of node asks. A data node's document names no such table, so a data
 * node never hands on its input: what it hands on is its load's.
 */
export function handsOnItsInput(spec: any): boolean {
    return loadedSources(spec).length === 0 || autkNeedsInput(spec);
}

/**
 * The tables of a node's input, *prepared* as a compute step reads them
 * (utils/autkInput `autkSourcesFrom` with `alias: false`, each under its own
 * name): each geojson table as it came, then each raster in the element it
 * came in (utils/grammarInput `rasterAsItCame`), named as the node reads it.
 * No pass computes over a raster, so a raster is never another table.
 */
export function inputTablesOf(prepared: PreparedAutkInput | null | undefined): HandOnTable[] {
    if (!prepared) return [];
    const tables: HandOnTable[] = prepared.sources.map((source) => ({
        name: source.outputTableName,
        type: source.layerType ?? 'polygons',
        geojson: source.geojsonObject,
        ...(source.workspace ? { workspace: source.workspace } : {}),
    }));
    const rasters: HandOnTable[] = prepared.rasters.map((raster) => {
        const element = rasterAsItCame(raster.payload);
        return {
            name: raster.outputTableName,
            type: RASTER_TABLE,
            // Its cells, which a count reads: the collection an Autark raster's envelope holds.
            geojson: 'envelope' in raster.payload ? raster.payload.envelope?.data : undefined,
            ...(raster.workspace ? { workspace: raster.workspace } : {}),
            asItCame: element?.layerName === raster.outputTableName ? element : { ...element, layerName: raster.outputTableName },
        };
    });
    return [...tables, ...rasters];
}

/**
 * The tables a node holds, in the order it hands them on: its input's
 * (*input*, `inputTablesOf`; none when it does not hand on its input), but one
 * a table of its data section (*own*) holds under the same key, then its own,
 * a table of the input a join or an update changed among them.
 */
export function heldTables(input: readonly HandOnTable[], own: readonly HandOnTable[]): HandOnTable[] {
    const ownKeys = new Set(own.map(keyOf));
    return [...input.filter((table) => !ownKeys.has(keyOf(table))), ...own];
}

/**
 * *tables* without those that hold no feature: autk-db loads no empty table,
 * and a node below would show it as an empty tab. A raster a node made holds
 * its cells in one feature; a raster of its input goes on as it came, whatever
 * the node holds of it (`asItCame`). Each table left out is said in the log,
 * after *said*.
 */
export function withRows<T extends HandOnTable>(tables: readonly T[], said: string): T[] {
    const empty = tables.filter((table) => table.asItCame === undefined && !hasFeatures(table.geojson));
    if (empty.length > 0) console.warn(said + empty.map((table) => table.name).join(', '));
    return tables.filter((table) => !empty.includes(table));
}

/**
 * The columns *passes* compute, which a node lifts to the top of the features
 * of a table they wrote: each GPGPU, windows or clusters pass's
 * `outputColumns`, else its `outputColumnName`. A render pass's shares stay
 * under `compute.render`.
 */
export function computedColumns(passes: readonly any[]): string[] {
    const columns: string[] = [];
    for (const pass of passes) {
        if (pass?.type === 'render') continue;
        const named = Array.isArray(pass?.outputColumns) ? pass.outputColumns : [pass?.outputColumnName];
        for (const column of named) {
            if (typeof column === 'string' && column !== '' && !columns.includes(column)) columns.push(column);
        }
    }
    return columns;
}

/**
 * *fc* with each of *columns* a feature holds under `compute`, and not at its
 * top, at its top too, so a node below reads a column a pass computed by its
 * bare name: `compute.<col>` and `<col>` both resolve. Each feature it changes
 * is a copy, and *fc* is left as it was; the same object when it changes none.
 */
export function withLiftedColumns(fc: any, columns: readonly string[]): any {
    const features: any[] = Array.isArray(fc?.features) ? fc.features : [];
    if (columns.length === 0 || features.length === 0) return fc;
    let changed = false;
    const next = features.map((feature) => {
        const properties = feature?.properties;
        const computed = properties?.compute;
        if (properties == null || typeof properties !== 'object' || computed == null || typeof computed !== 'object') {
            return feature;
        }
        const lifted = columns.filter((column) => column in computed && !(column in properties));
        if (lifted.length === 0) return feature;
        changed = true;
        return { ...feature, properties: { ...properties, ...Object.fromEntries(lifted.map((column) => [column, computed[column]])) } };
    });
    return changed ? { ...fc, features: next } : fc;
}

/**
 * The keys of the tables *after*'s drops drop and none of its later sources
 * makes again.
 */
export function droppedBy(after: readonly any[]): Set<string> {
    const dropped = new Set<string>();
    after.forEach((source, at) => {
        if (source?.type !== 'drop' || typeof source.dataRef !== 'string' || source.dataRef === '') return;
        const key = autkTableKey(autkWorkspaceOf(source), source.dataRef);
        if (!requestedLayerTables(after.slice(at + 1)).includes(key)) dropped.add(key);
    });
    return dropped;
}

/** A table as the passes of a node's run left it: the run's own collection, and its type when the run says. */
export type PassResult = { collection: any; layerType?: string };

/** Where a node's run keeps what it made, for `handOnTables`. */
export type HandOnRun = {
    /** The tables the node holds, in the order it hands them on (`heldTables`, `withRows`). */
    held: readonly HandOnTable[];
    /** The passes that ran, in their order. */
    passes: readonly any[];
    /** The sources after compute, in their order. */
    after?: readonly any[];
    /** The table *name* of *workspace* as the passes left it: undefined when none of them wrote it. */
    computed: (name: string, workspace: string | undefined) => PassResult | undefined | Promise<PassResult | undefined>;
    /** A table a source after compute wrote, as the run's database holds it, read back as the loaders hand one on. */
    readBack?: (name: string, workspace: string | undefined) => HandOnTable | undefined | Promise<HandOnTable | undefined>;
    /**
     * The CRS a table a pass wrote says (a GeoJSON `crs`), from *from*, the
     * table the node held that it was computed from, or from its workspace;
     * undefined leaves it as the pass left it.
     */
    crs: (collection: any, workspace: string | undefined, from: HandOnTable | undefined) => any;
    /**
     * *table* with each building's height as the node held it: *rows* is the
     * table the node held whose rows a table a pass wrote holds, if any. Read
     * for each table a pass wrote, and each a source after compute wrote.
     */
    heights?: (table: HandOnTable, rows: HandOnTable | undefined, how: 'computed' | 'read back') => HandOnTable;
};

/** The tables a node hands on, in order, from what its run made (see the module's description). */
export async function handOnTables(run: HandOnRun): Promise<HandOnTable[]> {
    const { held, passes } = run;
    const after = run.after ?? [];
    const heldByKey = new Map(held.map((table) => [keyOf(table), table]));
    // Each table a pass wrote, by key: the key of the held table whose rows it
    // holds ('' for none: windows), the held table it was computed from, and
    // its type, each followed through passes that write from one another.
    const written = writtenTables({ compute: passes });
    const rowsOf = new Map<string, string>();
    const originOf = new Map<string, string>();
    const typeOf = new Map<string, string | undefined>(held.map((table) => [keyOf(table), table.type]));
    for (const { name, from, holdsRows, layerType, workspace } of written) {
        const key = autkTableKey(workspace, name);
        const fromKey = autkTableKey(workspace, from);
        rowsOf.set(key, holdsRows ? rowsOf.get(fromKey) ?? fromKey : '');
        originOf.set(key, originOf.get(fromKey) ?? fromKey);
        typeOf.set(key, layerType ?? typeOf.get(fromKey));
    }
    const wroteAfter = new Set([...requestedLayerTables([...after]), ...sectionChangedTables([...after])]);
    const dropped = droppedBy(after);
    const columns = computedColumns(passes);
    const handed: HandOnTable[] = [];
    const listed = new Set<string>();
    const handOn = async (name: string, workspace: string | undefined, was?: HandOnTable) => {
        const key = autkTableKey(workspace, name);
        if (listed.has(key) || dropped.has(key)) return;
        listed.add(key);
        // A table a source after compute wrote is the database's now, a
        // table a pass wrote before it among them, with the columns the
        // passes computed lifted as in a table a pass wrote.
        if (wroteAfter.has(key) && run.readBack) {
            const read = await run.readBack(name, workspace);
            if (read) {
                const geojson = withLiftedColumns(read.geojson, columns);
                const table = geojson === read.geojson ? read : { ...read, geojson };
                handed.push(run.heights ? run.heights(table, undefined, 'read back') : table);
                return;
            }
        }
        const result = rowsOf.has(key) ? await run.computed(name, workspace) : undefined;
        if (result?.collection) {
            const collection = withLiftedColumns(result.collection, columns);
            const crs = run.crs(collection, workspace, heldByKey.get(originOf.get(key) ?? ''));
            const table: HandOnTable = {
                name,
                type: result.layerType ?? typeOf.get(key) ?? 'polygons',
                geojson: crs === undefined ? collection : { ...collection, crs },
                ...(workspace ? { workspace } : {}),
            };
            handed.push(run.heights ? run.heights(table, heldByKey.get(rowsOf.get(key) ?? ''), 'computed') : table);
            return;
        }
        if (was) handed.push(was);
    };
    for (const table of held) await handOn(table.name, table.workspace, table);
    for (const { name, workspace } of written) await handOn(name, workspace);
    for (const source of after) {
        const workspace = autkWorkspaceOf(source);
        for (const key of requestedLayerTables([source])) {
            await handOn(workspace === undefined ? key : key.slice(workspace.length + 1), workspace);
        }
    }
    return handed;
}

/**
 * *table*, which a pass of a node that draws wrote from autk-db's copy of a
 * table the node held (*rows*), as the node hands it on: with no mark of the
 * input row a feature stands for (utils/autkInput `INPUT_ROW`), which the
 * node's maps read and the nodes below do not; and where the node gave its run
 * a building of *rows* with no height the default (*defaulted*), each building
 * with the height it held again, when every feature names its own row of
 * *rows*, each row once (utils/autkInput `withHeightsAsHeld`). autk-db keeps a
 * table's rows in an order of its own, and a building as one feature of its
 * parts, which name no row of their own: such a table keeps its heights as the
 * run read them.
 */
export function asHandedFromTheRun(table: HandOnTable, rows: HandOnTable | undefined, defaulted: boolean): HandOnTable {
    const features: any[] = Array.isArray(table.geojson?.features) ? table.geojson.features : [];
    const held: any[] = Array.isArray(rows?.geojson?.features) ? rows!.geojson.features : [];
    let geojson = table.geojson;
    if (defaulted && features.length === held.length && features.length > 0) {
        const order = features.map((feature) => feature?.properties?.[INPUT_ROW]);
        const once = new Set(order);
        if (order.every((row) => Number.isInteger(row) && row >= 0 && row < held.length) && once.size === order.length) {
            geojson = withHeightsAsHeld(geojson, { type: 'FeatureCollection', features: order.map((row) => held[row]) } as any);
        }
    }
    const marked = (geojson?.features ?? []).some((feature: any) => feature?.properties != null && INPUT_ROW in feature.properties);
    if (marked) {
        geojson = {
            ...geojson,
            features: geojson.features.map((feature: any) => {
                if (feature?.properties == null || !(INPUT_ROW in feature.properties)) return feature;
                const { [INPUT_ROW]: _row, ...properties } = feature.properties;
                return { ...feature, properties };
            }),
        };
    }
    return geojson === table.geojson ? table : { ...table, geojson };
}

/**
 * The CRS a table read from autk-db says, a GeoJSON `crs`: its workspace's,
 * the coordinates autk-db keeps it in (autkDataCompile `layerEpsg`, from the
 * document's `workspaces` *crsOf*, else autk-db's default *fallback*).
 */
export function workspaceCrs(collection: any, workspace: string | undefined, crsOf: Record<string, string>, fallback: string): any {
    return { type: 'name', properties: { name: `urn:ogc:def:crs:EPSG::${layerEpsg(collection, workspace, crsOf, fallback)}` } };
}

/**
 * The table *name* of *workspace* a source after compute wrote, read back from
 * *db*, a run's autk-db database, as the loaders hand one on: in its
 * workspace, entered with *enterWorkspace* (autk-grammar's); a table with no
 * geometry as its rows (`plainTableRecord`); an OpenStreetMap table with its
 * OSM ids and its numeric tags as numbers (`withOsmIds`, `withOsmNumbers`); a
 * buildings table a part a row (`explodeBuildingParts`); each in its
 * workspace's CRS (`workspaceCrs`).
 */
export async function readBackTable(
    db: any,
    enterWorkspace: (db: any, workspace?: string) => Promise<void>,
    name: string,
    workspace: string | undefined,
    crsOf: Record<string, string>,
    fallback: string,
): Promise<HandOnTable> {
    await enterWorkspace(db, workspace);
    const table = (db.getTablesMetadata() as Array<{ name: string; type?: string; source?: string }>)
        .find((t) => t.name === name);
    if (table && table.type === undefined) {
        return plainTableRecord(name, await db.getTable(name), workspace) as HandOnTable;
    }
    const geojson: any = await db.getLayer(name);
    const type = table?.type ?? 'polygons';
    if (Array.isArray(geojson?.features)) geojson.features = withOsmNumbers(table, withOsmIds(table, geojson.features));
    if (type === 'buildings' && Array.isArray(geojson?.features)) geojson.features = explodeBuildingParts(geojson.features);
    if (geojson && typeof geojson === 'object') geojson.crs = workspaceCrs(geojson, workspace, crsOf, fallback);
    return { name, type, geojson, ...(workspace ? { workspace } : {}) };
}

/**
 * Each table *after*'s sources (a node's sources after compute) made or
 * changed, read back from *db*, the database the node's run went on, by its
 * key: a raster (a heatmap, a GeoTIFF) as autk-db's raster store holds it,
 * with the grid its cells lie on, as autkLayerMaterialize `grammarRaster`
 * reads one, so in the run's raster turn; any other table as the loaders hand
 * one on (`readBackTable`), in its workspace's CRS (*crsOf*, else the default
 * workspace's). A table a drop dropped is not read. The database is left in
 * the default workspace, where autk-grammar's `data` reads.
 */
export async function readBackAfterCompute(
    db: any,
    enterWorkspace: (db: any, workspace?: string) => Promise<void>,
    after: readonly any[],
    crsOf: Record<string, string>,
): Promise<Map<string, HandOnTable>> {
    const read = new Map<string, HandOnTable>();
    if (!db || after.length === 0) return read;
    const dropped = droppedBy(after);
    try {
        await enterWorkspace(db);
        const fallback = String(db.getWorkspaceConfiguration?.()?.coordinateFormat ?? 'EPSG:3395');
        for (const source of after) {
            const workspace = autkWorkspaceOf(source);
            for (const key of [...requestedLayerTables([source]), ...sectionChangedTables([source])]) {
                if (read.has(key) || dropped.has(key)) continue;
                const name = workspace === undefined ? key : key.slice(workspace.length + 1);
                if (GRAMMAR_RASTER_SOURCES.includes(source?.type) && name === source.outputTableName) {
                    await enterWorkspace(db, workspace);
                    const crs = db.getWorkspaceConfiguration().coordinateFormat;
                    read.set(key, {
                        name, type: RASTER_TABLE, geojson: withRasterGrid(await db.getRaster(name), crs),
                        ...(workspace ? { workspace } : {}),
                    });
                } else {
                    read.set(key, await readBackTable(db, enterWorkspace, name, workspace, crsOf, fallback));
                }
            }
        }
    } finally {
        await enterWorkspace(db);
    }
    return read;
}

/**
 * What a node hands on of *tables*, as a compute step does (autkLayerMaterialize
 * `toPoolOutput`): kept in the sandbox and handed on by its reference; for a
 * step a dashboard viewer's run asked of the page, kept for that run; with no
 * JavaScript interpreter, inline; and *tables* themselves when there is none.
 *
 * On a dashboard page (*onDashboard*), what no viewer's run asked of the page
 * goes on inline: a viewer has no session to keep anything with in the
 * sandbox, so a draw asks it nothing.
 *
 * With *stored*, the hand-on the node kept in the sandbox last: tables the same
 * as those (a node that draws, drawn again for a color edit) go on as that
 * output again, and nothing is sent to the sandbox (autkLayerMaterialize
 * `StoredHandOn`).
 */
export async function handOnOutput(
    tables: HandOnTable[],
    { jsInterpreter, nodeId, onDashboard = false, stored }: {
        jsInterpreter: JavaScriptInterpreter | undefined;
        nodeId: string;
        onDashboard?: boolean;
        stored?: { current: StoredHandOn | null };
    },
): Promise<any> {
    return (await toPoolOutput(tables, onDashboard ? undefined : jsInterpreter, nodeId, stored)) ?? tables;
}
