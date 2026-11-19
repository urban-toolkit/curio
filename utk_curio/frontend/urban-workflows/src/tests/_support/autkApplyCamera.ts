/**
 * autk-grammar's own `applyCamera(map, camera)`, for the tests of how an
 * Autark node turns a map by the `camera` its document writes
 * (adapters/node/autkMapView): the function the node takes from the grammar it
 * runs. It is read from the grammar's CommonJS build, which loads with the five
 * packages it imports stubbed: as it loads, the build reads only autk-core's
 * `ColorMapInterpolator` (its plot options list the color schemes), which
 * autk-core's stub holds (`autkCoreAtLoad`), and `applyCamera` reads and
 * resets only the map's camera. A suite that reads it stubs them first,
 * virtually, as every suite mocks them (tests/mockKinds.test.ts):
 *
 *     jest.mock("@urban-toolkit/autk-db", () => ({}), { virtual: true });
 *     jest.mock("@urban-toolkit/autk-map", () => ({}), { virtual: true });
 *     jest.mock("@urban-toolkit/autk-plot", () => ({}), { virtual: true });
 *     jest.mock("@urban-toolkit/autk-core", () => require("../../_support/autkApplyCamera").autkCoreAtLoad(), { virtual: true });
 *     jest.mock("@urban-toolkit/autk-compute", () => ({}), { virtual: true });
 */
import * as path from 'path';

/** autk-grammar's `applyCamera`: turns *map*'s camera as *camera* says. */
export type ApplyCamera = (map: any, camera: Record<string, unknown>) => void;

/** The grammar's CommonJS build, as the frontend installs it. */
const GRAMMAR_BUILD = path.resolve(
  __dirname, '../../../node_modules/@urban-toolkit/autk-grammar/dist/autk-grammar.umd.cjs',
);

/** autk-core's CommonJS build, as the frontend installs it. */
const AUTK_CORE_BUILD = path.resolve(
  __dirname, '../../../node_modules/@urban-toolkit/autk-core/dist/autk-core.umd.cjs',
);

/**
 * autk-core's stub for a suite that reads the grammar's build: the real
 * `ColorMapInterpolator` alone, the one export the build reads as it loads.
 */
export function autkCoreAtLoad(): { ColorMapInterpolator: Record<string, string> } {
  const { ColorMapInterpolator } = jest.requireActual(AUTK_CORE_BUILD) as {
    ColorMapInterpolator: Record<string, string>;
  };
  return { ColorMapInterpolator };
}

/** The grammar build's `applyCamera`; fails when the build exports none. */
export function grammarApplyCamera(): ApplyCamera {
  const { applyCamera } = jest.requireActual(GRAMMAR_BUILD) as { applyCamera?: ApplyCamera };
  if (typeof applyCamera !== 'function') {
    throw new Error(`autk-grammar's build at ${GRAMMAR_BUILD} exports no applyCamera`);
  }
  return applyCamera;
}
