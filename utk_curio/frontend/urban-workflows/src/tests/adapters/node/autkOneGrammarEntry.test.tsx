/**
 * One run of an Autark node reads its tables through one entry of
 * autk-grammar. The grammar's `./data` entry is a bundle of its own: it keeps
 * its own copy of the note a GeoJSON source leaves on the collection it put in
 * the data adapter's cache, with its CRS, which a compute pass reads before it
 * reads a `fromFeature` table from that cache. So a compute adapter of the main
 * entry handed a cache a data adapter of `./data` filled finds no note, reads
 * autk-db's copy of each building, a GeometryCollection, and computes zeros,
 * without an error (found on autarkjs.org #8).
 *
 * - No module of the app takes from both entries, and no compute adapter it
 *   makes is handed a data adapter's cache: the loaders take `./data`, which
 *   loads without autk-map, autk-plot and autk-compute, and a map node's run
 *   and a compute step take the main entry.
 * - A map node's run hands each of its compute passes the run's own database:
 *   the grammar's compute reads a `fromFeature` table from the cache its own
 *   data adapter filled, of the same entry, and the node reads no table for it.
 *
 * Read with the TypeScript parser, as the other source guards read the files,
 * so an import written in a comment is no import. The node's run draws with
 * the stand-in grammar of _support/autkNodeMocks.
 */
jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({
  JavaScriptInterpreter: class { },
}));
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => require('../../_support/autkNodeMocks').autkGrammarModule,
  { virtual: true },
);
// autk-compute's device, on which each pass runs in error scopes.
jest.mock('@urban-toolkit/autk-compute', () => require('../../_support/autkComputeStandIns').autkComputeModule, { virtual: true });

import fs from 'fs';
import path from 'path';
import ts from 'typescript';
import { compileDataSpecToAutkDbJs } from '../../../adapters/node/autkDataCompile';
import {
  AutkGrammar,
  drawnExports,
  grammarComputes,
  grammarRuns as mockRuns,
  inputsByPath,
  resetAutkNodeMocks,
} from '../../_support/autkNodeMocks';
import { mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';

const SRC = path.resolve(__dirname, '../../..');
const MAIN = '@urban-toolkit/autk-grammar';
const DATA = '@urban-toolkit/autk-grammar/data';

/** Every TypeScript file of the app under src/, its tests left out. */
function appFiles(dir: string = SRC): string[] {
  const files: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== 'tests') files.push(...appFiles(full));
    } else if (/\.tsx?$/.test(entry.name) && !/\.d\.ts$/.test(entry.name)) {
      files.push(full);
    }
  }
  return files;
}

/** The grammar entries *file* imports, statically or with import(), and its calls of createComputeAdapter. */
function grammarUses(file: string): { entries: Set<string>; computeAdapterArgs: number[] } {
  const text = fs.readFileSync(file, 'utf8');
  const kind = file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const entries = new Set<string>();
  const computeAdapterArgs: number[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isImportDeclaration(node) && ts.isStringLiteralLike(node.moduleSpecifier)) {
      if ([MAIN, DATA].includes(node.moduleSpecifier.text) && !node.importClause?.isTypeOnly) entries.add(node.moduleSpecifier.text);
    }
    if (ts.isCallExpression(node)) {
      const [specifier] = node.arguments;
      if (node.expression.kind === ts.SyntaxKind.ImportKeyword && specifier && ts.isStringLiteralLike(specifier)
        && [MAIN, DATA].includes(specifier.text)) {
        entries.add(specifier.text);
      }
      const callee = node.expression;
      const name = ts.isIdentifier(callee) ? callee.text : ts.isPropertyAccessExpression(callee) ? callee.name.text : '';
      if (name === 'createComputeAdapter') computeAdapterArgs.push(node.arguments.length);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return { entries, computeAdapterArgs };
}

const relative = (file: string) => path.relative(SRC, file).split(path.sep).join('/');

describe("a run takes autk-grammar's tables and compute from one entry", () => {
  test('no module of the app takes from both entries of autk-grammar', () => {
    const both = appFiles().filter((file) => grammarUses(file).entries.size > 1).map(relative);
    expect(both).toEqual([]);
  });

  test('the loaders take the data entry, and a map node and a compute step the main entry', () => {
    const entriesOf = (file: string) => [...grammarUses(path.join(SRC, file)).entries];
    expect(entriesOf('adapters/node/autkLayerMaterialize.ts')).toEqual([DATA]);
    expect(entriesOf('adapters/node/autkGrammarBehavior.tsx')).toEqual([MAIN]);
    expect(entriesOf('adapters/node/autkComputeBlocks.ts')).toEqual([MAIN]);
    // The sandbox's code imports the data entry alone.
    const code = compileDataSpecToAutkDbJs([{ type: 'csv', outputTableName: 'sales', csvObject: [['month'], ['Jan']] }]);
    const imported = [...code.matchAll(/from '([^']+)'/g)].map((found) => found[1]);
    expect(imported.filter((name) => name.startsWith(MAIN))).toEqual([DATA]);
  });

  test("no compute adapter the app makes is handed a data adapter's cache", () => {
    const handed = appFiles().flatMap((file) => grammarUses(file).computeAdapterArgs
      .filter((count) => count > 2).map((count) => `${relative(file)}: ${count} arguments`));
    expect(handed).toEqual([]);
  });
});

describe("a map node's compute passes read the run's own database", () => {
  /** Two buildings and a street, as an upstream Autark node hands them on. */
  const BLOCKS = [12, 30].map((height, i) => ({
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [[[i, 0], [i + 1, 0], [i + 1, 1], [i, 0]]] },
    properties: { height },
  }));
  const STREETS = [{ type: 'Feature', geometry: { type: 'LineString', coordinates: [[0, 0], [2, 0]] }, properties: { value: 1 } }];
  const RECORDS = [
    { name: 'blocks', type: 'buildings', geojson: { type: 'FeatureCollection', features: BLOCKS } },
    { name: 'streets', type: 'roads', geojson: { type: 'FeatureCollection', features: STREETS } },
  ];

  beforeEach(() => {
    resetAutkNodeMocks();
    stubWebGpu();
    inputsByPath.current = { 'art-one-entry': { dataType: 'list', data: RECORDS } };
  });

  afterEach(unstubWebGpu);

  test("each pass is handed the run's database, through which the node reads no table", async () => {
    const handed: any[] = [];
    const blocksRead: number[] = [];
    // autk-db exports no row of the blocks, and the streets as handed: a
    // read of the blocks through the run's database finds none.
    drawnExports.of = (table, rows) => (table === 'blocks' ? [] : rows);
    grammarComputes.on = true;
    grammarComputes.adapter = () => ({
      resolveCompute: jest.fn(async (context: any) => {
        handed.push(context);
        blocksRead.push((await context.getLayer('blocks')).features.length);
        return context;
      }),
    });
    const node = mountAutkNode('one-entry', undefined, { input: { path: 'art-one-entry', dataType: 'list' } });
    await node.run({
      compute: [{
        dataRef: 'streets', attributes: { value: 'value' }, wgslFunction: 'return value;', outputColumnName: 'sun',
        uniforms: { bld_height: { fromFeature: { layer: 'blocks', iterate: 'batched', path: 'properties.height', required: true } } },
      }],
      map: { layerRefs: [{ dataRef: 'streets', getFnv: 'compute.sun' }] },
    });

    expect(node.lastOutput()).toMatchObject({ code: 'success' });
    expect(mockRuns).toHaveLength(1);
    // The pass was handed the database the run made, and read the blocks as
    // that database holds them: the node handed it no copy of its own.
    const runDatabase = (AutkGrammar.mock.results[0].value as any).grammarEngine?.context;
    expect(handed).toHaveLength(1);
    expect(handed[0]).toBe(runDatabase);
    expect(blocksRead).toEqual([0]);
  });
});
