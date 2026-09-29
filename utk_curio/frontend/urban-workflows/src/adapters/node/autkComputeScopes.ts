/**
 * A compute pass the GPU refused must fail its block, not return zeros.
 *
 * ``ComputeGpgpu.run`` never throws for a shader or pipeline the GPU refuses:
 * WebGPU reports it as an error on the device, ``createComputePipeline`` hands
 * back an invalid pipeline, the dispatch does nothing, and the read-back buffer
 * still holds zeros, which ``run`` writes into every feature. Example 07's
 * sunlight column came out the same for every road that way, under a green
 * Done, on a driver that could not build its pipeline. Error scopes around the
 * dispatch are the only place that refusal can be seen.
 *
 * The device is autk-compute's own, shared by every ``ComputeGpgpu``;
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

/** ``gpgpu.run(params)``, failing when the GPU reported an error meanwhile. */
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
