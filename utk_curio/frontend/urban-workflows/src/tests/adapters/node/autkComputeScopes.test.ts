import { runComputeChecked } from '../../../adapters/node/autkComputeScopes';

/**
 * A compute pass the GPU refused used to return zeros under a green Done:
 * example 07's sunlight came out the same for every road. WebGPU reports that
 * refusal only on the device, so the check reads the device's error scopes.
 */

type Scope = 'validation' | 'internal' | 'out-of-memory';

function fakeGpgpu(
    caught: Partial<Record<Scope, string>>,
    run: () => Promise<unknown> = async () => ({ type: 'FeatureCollection', features: [] }),
) {
    const pushed: Scope[] = [];
    const device = {
        pushErrorScope: jest.fn((scope: Scope) => pushed.push(scope)),
        popErrorScope: jest.fn(async () => {
            const scope = pushed.pop()!;
            return caught[scope] ? { message: caught[scope]! } : null;
        }),
    };
    return { device, gpgpu: { run: jest.fn(run), getDevice: async () => device } };
}

describe('runComputeChecked', () => {
    it('returns the pass when the GPU reported nothing', async () => {
        const out = { type: 'FeatureCollection', features: [{ id: 1 }] };
        const { device, gpgpu } = fakeGpgpu({}, async () => out);
        await expect(runComputeChecked(gpgpu, { any: 'params' })).resolves.toBe(out);
        expect(device.pushErrorScope).toHaveBeenCalledTimes(3);
        expect(device.popErrorScope).toHaveBeenCalledTimes(3);
    });

    it('fails with the GPU\'s reason when it refused the pipeline', async () => {
        const { gpgpu } = fakeGpgpu({
            internal: 'CreateComputePipelines failed with VK_ERROR_UNKNOWN\n - While initializing [ComputePipeline]',
        });
        await expect(runComputeChecked(gpgpu, {})).rejects.toThrow(
            'the GPU could not run this compute pass: CreateComputePipelines failed with VK_ERROR_UNKNOWN',
        );
    });

    it('names the driver\'s refusal, not the validation errors that follow it', async () => {
        const { gpgpu } = fakeGpgpu({
            internal: 'Error creating pipeline state Compute function exceeds available stack space',
            validation: '[Invalid ComputePipeline (unlabeled)] is invalid due to a previous error.',
        });
        await expect(runComputeChecked(gpgpu, {})).rejects.toThrow(/exceeds available stack space/);
    });

    it('fails on a validation error alone', async () => {
        const { gpgpu } = fakeGpgpu({ validation: 'Binding size is smaller than the minimum' });
        await expect(runComputeChecked(gpgpu, {})).rejects.toThrow(/Binding size/);
    });

    it('rethrows the run\'s own error and still closes every scope', async () => {
        const { device, gpgpu } = fakeGpgpu({}, async () => { throw new Error('resultField or outputColumns must be provided'); });
        await expect(runComputeChecked(gpgpu, {})).rejects.toThrow('resultField or outputColumns must be provided');
        expect(device.popErrorScope).toHaveBeenCalledTimes(3);
    });
});
