/**
 * autk-grammar's own `applyCamera(map, camera)`, for the tests of how an
 * Autark node turns a map by the `camera` its document writes
 * (adapters/node/autkMapView): the function the node takes from the grammar it
 * runs. It is read from the grammar's CommonJS build, which loads with the five
 * packages it imports stubbed: the build reads none of them while it loads, and
 * `applyCamera` reads and resets only the map's camera. A suite that reads it
 * stubs them first:
 *
 *     jest.mock("@urban-toolkit/autk-db", () => ({}), { virtual: true });
 *     jest.mock("@urban-toolkit/autk-map", () => ({}), { virtual: true });
 *     jest.mock("@urban-toolkit/autk-plot", () => ({}), { virtual: true });
 *     jest.mock("@urban-toolkit/autk-core", () => ({}), { virtual: true });
 *     jest.mock("@urban-toolkit/autk-compute", () => ({}), { virtual: true });
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
