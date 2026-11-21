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
 * Every pass Curio runs, a map node's in the grammar's run (its grammar takes
 * ``checkedPasses`` as its ``wrapComputeAdapter``, autk-grammar 5.6.0) and a
 * compute step's, goes through ``checkedPasses``: in error scopes on the
 * device, one pass at a time on the page, named by the table it writes when
 * it fails. A
 * windows or clusters pass, which the grammar runs on the CPU, asks no device:
 * it runs as it is, named the same way when it fails.
 *
 * The device is autk-compute's own, shared by every one of its pipelines;
 * ``getDevice`` is protected in its types, hence the cast.
 */

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
 * ``AutkGrammar`` hands it to ``wrapComputeAdapter``, or its compute steps
 * (``createComputeSteps``): ``resolveCompute`` runs one pass of a document.
 */
export interface PassAdapter {
    resolveCompute(context: unknown, pass: any): Promise<unknown>;
}

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

/** The table *pass* writes: its `outputTableName`, else a GPGPU or clusters pass's `dataRef`. */
function tableWrittenBy(pass: any): string {
    const name = pass?.outputTableName ?? (pass?.type === 'render' ? undefined : pass?.dataRef);
    return typeof name === 'string' && name ? name : 'compute';
}

/**
 * The passes autk-grammar runs on the CPU, through autk-core, with no GPU: a
 * windows pass and a clusters pass (autk-grammar 5.4.0).
 */
const CPU_PASSES: ReadonlySet<unknown> = new Set(['windows', 'clusters']);

/**
 * *adapter* with every pass it runs checked: in error scopes on autk-compute's
 * device (``runComputeChecked``), one pass at a time on the page. A pass the
 * grammar runs on the CPU asks no device and runs as it is. A pass that
 * fails, the GPU refusing it or the grammar, is named by the table it writes.
 * Each pass runs on the database it was given, as autk-grammar's engine hands
 * it on: the grammar's compute reads a `fromFeature` table from the cache of
 * its own data adapter, which the node's handed GeoJSON fills, so no table is
 * read for it here.
 */
export function checkedPasses(adapter: PassAdapter): PassAdapter {
    const named = async <T>(pass: any, run: () => Promise<T>): Promise<T> => {
        try {
            return await run();
        } catch (e) {
            throw new Error(`${tableWrittenBy(pass)}: ${e instanceof Error ? e.message : String(e)}`);
        }
    };
    return {
        resolveCompute: (context, pass) => {
            if (CPU_PASSES.has(pass?.type)) return named(pass, () => adapter.resolveCompute(context, pass));
            const compute = {
                getDevice: computeDevice,
                run: (params: any) => adapter.resolveCompute(context, params),
            };
            return onePassAtATime(() => named(pass, () => runComputeChecked(compute, pass)));
        },
    };
}
