/**
 * A compute pass the GPU refused must fail its block, not return zeros.
 *
 * WebGPU never throws for a shader or pipeline the GPU refuses: it reports it
 * as an error on the device, ``createComputePipeline`` hands back an invalid
 * pipeline, the dispatch does nothing, and the read-back buffer still holds
 * zeros, which autk-compute writes into every feature. Example 07's sunlight
 * column came out the same for every road that way, under a green Done, on a
 * driver that could not build its pipeline. Error scopes around the pass are
 * the only place that refusal can be seen. autk-compute's render pipeline
 * opens none of its own, so a render pass the GPU refused would count nothing.
 *
 * Every pass Curio runs, a map node's in the grammar's run and a compute
 * step's, goes through ``checkedPasses``: in error scopes on the device, one
 * pass at a time on the page, named by the table it writes when it fails.
 *
 * The device is autk-compute's own, shared by every one of its pipelines;
 * ``getDevice`` is protected in its types, hence the cast.
 */

import type { FeatureCollection } from 'geojson';
import { autkTableKey, autkWorkspaceOf } from './autkDataCompile';

interface GpuErrorLike {
    message: string;
}

interface ScopedDevice {
    pushErrorScope(filter: 'validation' | 'internal' | 'out-of-memory'): void;
    popErrorScope(): Promise<GpuErrorLike | null>;
}

/** The part of ``ComputeGpgpu`` a checked run needs. */
export interface CheckedCompute<P, R> {
    run(params: P): Promise<R>;
}

// Pushed in this order, so popped in reverse.
const SCOPES = ['validation', 'internal', 'out-of-memory'] as const;
// The error to name first: an internal one is the driver's refusal; the
// validation ones that follow only say something was "invalid due to a
// previous error".
const PRECEDENCE = ['internal', 'out-of-memory', 'validation'] as const;

function firstLine(text: string): string {
    return (text.split('\n').find((line) => line.trim()) ?? text).trim();
}

/** ``gpgpu.run(params)``, failing when the GPU reported an error on its device meanwhile. */
export async function runComputeChecked<P, R>(
    gpgpu: CheckedCompute<P, R>,
    params: P,
): Promise<R> {
    const device = await (gpgpu as unknown as { getDevice(): Promise<ScopedDevice> }).getDevice();
    for (const scope of SCOPES) device.pushErrorScope(scope);
    let result: R | undefined;
    let thrown: unknown = null;
    try {
        result = await gpgpu.run(params);
    } catch (e) {
        thrown = e;
    }
    const caught: Partial<Record<(typeof SCOPES)[number], GpuErrorLike>> = {};
    for (const scope of [...SCOPES].reverse()) {
        const error = await device.popErrorScope();
        if (error) caught[scope] = error;
    }
    if (thrown) throw thrown;
    const first = PRECEDENCE.map((scope) => caught[scope]).find(Boolean);
    if (first) {
        throw new Error(`the GPU could not run this compute pass: ${firstLine(first.message)}`);
    }
    return result as R;
}

/**
 * autk-grammar's compute adapter, as ``createComputeAdapter`` makes it and an
 * ``AutkGrammar`` keeps it: ``resolveCompute`` runs one pass of a document.
 */
export interface PassAdapter {
    resolveCompute(context: unknown, pass: any): Promise<unknown>;
}

/** What a map node says when its grammar keeps no compute adapter where Curio checks its passes. */
export const COMPUTE_ADAPTER_MISSING =
    'Autark cannot run these compute passes: this autk-grammar build runs them differently, '
    + "and Curio's check of each pass (adapters/node/autkComputeScopes.ts) has to follow it.";

// The error scopes are the device's: two passes in them at once would each
// read the other's errors. Every checked pass on the page waits for the last.
let checkedRuns: Promise<unknown> = Promise.resolve();

function onePassAtATime<T>(run: () => Promise<T>): Promise<T> {
    const next = checkedRuns.then(run, run);
    checkedRuns = next.catch(() => undefined);
    return next;
}

/** autk-compute's device, shared by every one of its pipelines. */
async function computeDevice(): Promise<ScopedDevice> {
    const { ComputeGpgpu } = await import('@urban-toolkit/autk-compute');
    return (new ComputeGpgpu() as unknown as { getDevice(): Promise<ScopedDevice> }).getDevice();
}

/** The table *pass* writes: its `outputTableName`, else a GPGPU pass's `dataRef`. */
function tableWrittenBy(pass: any): string {
    const name = pass?.outputTableName ?? (pass?.type === 'render' ? undefined : pass?.dataRef);
    return typeof name === 'string' && name ? name : 'compute';
}

/** The tables a node hands autk-grammar's run as GeoJSON, by key (``autkTableKey``). */
export type HandedTables = ReadonlyMap<string, FeatureCollection>;

/** The GeoJSON tables of *spec*'s `data`, by key: what a node hands the grammar's run. */
export function handedTables(spec: any): HandedTables {
    const sources: any[] = Array.isArray(spec?.data) ? spec.data : [];
    return new Map(sources
        .filter((source) => source?.type === 'geojson' && typeof source.outputTableName === 'string'
            && Array.isArray(source.geojsonObject?.features))
        .map((source) => [autkTableKey(autkWorkspaceOf(source), source.outputTableName), source.geojsonObject]));
}

/** The tables *pass* reads through `fromFeature`, its `dataRef` left out. */
function fromFeatureTables(pass: any): Set<string> {
    const names = new Set<string>();
    for (const group of [pass?.uniforms, pass?.uniformMatrices]) {
        for (const value of Object.values(group ?? {})) {
            const layer = (value as any)?.fromFeature?.layer;
            if (typeof layer === 'string' && layer && layer !== pass?.dataRef) names.add(layer);
        }
    }
    return names;
}

/**
 * The database *pass* reads, with each table it reads through `fromFeature`,
 * but its `dataRef`, read as the node handed it (*handed*), in the pass's
 * workspace. autk-grammar's compute reads a table no pass wrote from autk-db,
 * which stores a building as a GeometryCollection of its parts, so the node
 * hands the pass such a table as it loaded it until the grammar reads a handed
 * table itself.
 */
function readingHandedTables(db: any, pass: any, handed: HandedTables): any {
    const names = fromFeatureTables(pass);
    if (names.size === 0 || typeof db?.getLayer !== 'function') return db;
    const workspace = autkWorkspaceOf(pass);
    const getLayer = async (name: string, ...rest: unknown[]) =>
        (names.has(name) ? handed.get(autkTableKey(workspace, name)) : undefined) ?? db.getLayer(name, ...rest);
    return new Proxy(db, {
        get(target, key) {
            if (key === 'getLayer') return getLayer;
            const value = Reflect.get(target, key, target);
            return typeof value === 'function' ? value.bind(target) : value;
        },
    });
}

/**
 * *adapter* with every pass it runs checked: in error scopes on autk-compute's
 * device (``runComputeChecked``), one pass at a time on the page. A pass that
 * fails, the GPU refusing it or the grammar, is named by the table it writes.
 * With *handed*, a pass reads its `fromFeature` tables as the node handed them
 * (``readingHandedTables``), and the database it was given goes on to the next.
 */
export function checkedPasses(adapter: PassAdapter, handed?: HandedTables): PassAdapter {
    return {
        resolveCompute: (context, pass) => onePassAtATime(async () => {
            const db = handed ? readingHandedTables(context, pass, handed) : context;
            const compute = {
                getDevice: computeDevice,
                run: (params: any) => adapter.resolveCompute(db, params),
            };
            try {
                const resolved = await runComputeChecked(compute, pass);
                return resolved === db ? context : resolved;
            } catch (e) {
                throw new Error(`${tableWrittenBy(pass)}: ${e instanceof Error ? e.message : String(e)}`);
            }
        }),
    };
}

/**
 * Let one grammar instance run each pass of its document checked
 * (``checkedPasses``), as a compute step runs its passes: autk-grammar runs
 * them through the compute adapter it keeps. *handed* is the tables the node
 * hands the run (``handedTables``), which a pass reads its `fromFeature`
 * tables from.
 */
export function withCheckedPasses(grammar: any, handed?: HandedTables): void {
    const adapter = grammar?.computeAdapter;
    if (!adapter || typeof adapter.resolveCompute !== 'function') throw new Error(COMPUTE_ADAPTER_MISSING);
    grammar.computeAdapter = checkedPasses(adapter, handed);
}
