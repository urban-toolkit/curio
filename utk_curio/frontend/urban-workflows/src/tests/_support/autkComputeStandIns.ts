/**
 * What a suite that runs Autark compute passes stands autk-compute in with,
 * and the autk-grammar build the app bundles, which runs them: its
 * `runCompute`, `createComputeAdapter` and `tableKey` are the grammar's own.
 * jsdom has no WebGPU, so the stand-in hands each GPGPU dispatch and each
 * render pipeline run to `computeRuns`, which a suite sets, and its device
 * reports in an error scope the GPU error a suite sets in `gpuErrors`. Free of
 * app imports, so a `jest.mock` factory can require it. Autark's packages are
 * mocked virtually, as every suite mocks them (tests/mockKinds.test.ts):
 *
 *     jest.mock("@urban-toolkit/autk-grammar", () => require("<this file>").grammarBuild(), { virtual: true });
 *     jest.mock("@urban-toolkit/autk-compute", () => require("<this file>").autkComputeModule, { virtual: true });
 *     jest.mock("@urban-toolkit/autk-core", () => require("<this file>").autkCoreBuild(), { virtual: true });
 *     jest.mock("@urban-toolkit/autk-map", () => require("<this file>").autkMapModule, { virtual: true });
 *     jest.mock("@urban-toolkit/autk-plot", () => require("<this file>").autkPlotModule, { virtual: true });
 *
 * The grammar build reads autk-db too, which each suite stands in itself.
 */
import * as path from 'path';

/** Autark's packages, as the app installs them. */
const AUTARK = path.resolve(__dirname, '../../../node_modules/@urban-toolkit');

type Scope = 'validation' | 'internal' | 'out-of-memory';

/**
 * Each GPGPU dispatch and each render pipeline run, with the parameters
 * autk-compute was handed; each answers what its function answers. A GPGPU
 * dispatch hands its collection back, and a render run its viewpoints'
 * collection, unless a suite says otherwise.
 */
export const computeRuns = {
  gpgpu: jest.fn(async (params: any): Promise<any> => params.collection),
  render: jest.fn(async (params: any): Promise<any> => params.viewpoints.collection),
};

/** The GPU error each error scope reports when it is popped; none unless a suite sets one. */
export const gpuErrors: { next: Partial<Record<Scope, string>> } = { next: {} };

const scopes: Scope[] = [];

/** autk-compute's shared device: the error scopes a run pushes and pops. */
export const computeDevice = {
  pushErrorScope: jest.fn((scope: Scope) => {
    scopes.push(scope);
  }),
  popErrorScope: jest.fn(async () => {
    const scope = scopes.pop();
    const message = scope ? gpuErrors.next[scope] : undefined;
    return message ? { message } : null;
  }),
};

/** A pipeline of autk-compute: every one runs on its shared device. */
class StandInPipeline {
  async getDevice() {
    return computeDevice;
  }
}

/** autk-compute, as the stand-in: its pipelines and its engine. */
export const autkComputeModule = {
  ComputeGpgpu: class extends StandInPipeline {
    run(params: any) {
      return computeRuns.gpgpu(params);
    }
  },
  ComputeRender: class extends StandInPipeline {
    run(params: any) {
      return computeRuns.render(params);
    }
  },
  AutkComputeEngine: class {
    gpgpuPipeline(params: any) {
      return computeRuns.gpgpu(params);
    }
    renderPipeline(params: any) {
      return computeRuns.render(params);
    }
  },
};

/** The autk-grammar build the app bundles, as CommonJS. */
export function grammarBuild(): any {
  return require(`${AUTARK}/autk-grammar/dist/autk-grammar.umd.cjs`);
}

/**
 * autk-core, as CommonJS: its package names its ES build before its CommonJS
 * one, so the grammar gets this one, as the other tests of Autark's builds do.
 */
export function autkCoreBuild(): any {
  return jest.requireActual(`${AUTARK}/autk-core/dist/autk-core.umd.cjs`);
}

/** autk-map and autk-plot: what the grammar build reads of them as it loads. */
export const autkMapModule = {
  AutkMap: class {},
  MapEvent: { PICKING: 'picking' },
};
export const autkPlotModule = {
  PlotEvent: { CLICK: 'click', BRUSH: 'brush', BRUSH_X: 'brushX', BRUSH_Y: 'brushY' },
};

/** Forget the last test's runs, scopes and GPU errors, and answer as by default. */
export function resetComputeStandIns(): void {
  computeRuns.gpgpu.mockReset();
  computeRuns.gpgpu.mockImplementation(async (params: any) => params.collection);
  computeRuns.render.mockReset();
  computeRuns.render.mockImplementation(async (params: any) => params.viewpoints.collection);
  gpuErrors.next = {};
  scopes.length = 0;
  computeDevice.pushErrorScope.mockClear();
  computeDevice.popErrorScope.mockClear();
}
