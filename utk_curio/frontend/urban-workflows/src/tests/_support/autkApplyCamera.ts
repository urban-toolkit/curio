/**
 * autk-grammar's own `applyCamera(map, camera)`, for the tests of how an
 * Autark node turns a map by the `camera` its document writes
 * (adapters/node/autkMapView): the function the node takes from the grammar it
 * runs. It is read from the grammar's CommonJS build, which loads with the five
 * packages it imports stubbed: the build reads none of them while it loads, and
 * `applyCamera` reads and resets only the map's camera. A suite that reads it
 * stubs them first, with plain mocks, never virtual ones:
 *
 *     jest.mock("@urban-toolkit/autk-db", () => ({}));
 *     jest.mock("@urban-toolkit/autk-map", () => ({}));
 *     jest.mock("@urban-toolkit/autk-plot", () => ({}));
 *     jest.mock("@urban-toolkit/autk-core", () => ({}));
 *     jest.mock("@urban-toolkit/autk-compute", () => ({}));
 *
 * autkPointSize.test.ts loads the same build with plain mocks of them, and a
 * Jest worker keeps, for every file it runs, the module id it first found for
 * the build's require of each: a virtual mock in one suite and a plain one in
 * another leave the build's require in whichever runs second to the installed
 * package, an ES module Jest cannot load (autkGrammarBuildMocks.test.ts). A
 * suite that also mounts a node keeps the node off these packages' own code
 * (a data section, a compute pass, a raster), which the other node suites
 * mock virtually.
 */
import * as path from 'path';

/** autk-grammar's `applyCamera`: turns *map*'s camera as *camera* says. */
export type ApplyCamera = (map: any, camera: Record<string, unknown>) => void;

/** The grammar's CommonJS build, as the frontend installs it. */
const GRAMMAR_BUILD = path.resolve(
  __dirname, '../../../node_modules/@urban-toolkit/autk-grammar/dist/autk-grammar.umd.cjs',
);

/** The grammar build's `applyCamera`; fails when the build exports none. */
export function grammarApplyCamera(): ApplyCamera {
  const { applyCamera } = jest.requireActual(GRAMMAR_BUILD) as { applyCamera?: ApplyCamera };
  if (typeof applyCamera !== 'function') {
    throw new Error(`autk-grammar's build at ${GRAMMAR_BUILD} exports no applyCamera`);
  }
  return applyCamera;
}
