/**
 * Every module the Jest suites mock is mocked one way across all of them:
 * virtually everywhere, or plainly everywhere. A support module's mocks
 * count too, since its jest.mock calls run in each suite that loads it.
 *
 * A Jest worker keeps one resolver for every file it runs. The resolver keeps
 * the module id it first worked out for a file's require of a name: the name
 * itself under a virtual mock, the module's file under a plain one. When one
 * suite mocks a module virtually and another plainly, and both require it from
 * one file, the require in whichever runs second in a worker finds the other's
 * id. None of its own mocks is under that id, so the real module loads.
 * autk-grammar's build did that to autk-db, an ES module Jest cannot read
 * ("Cannot use import statement outside a module"). autkPointSize.test.ts
 * failed to run in run 44339134488, and autkNodeCamera.test.tsx in run
 * 44341322614, as the order fell.
 *
 * Read with the TypeScript parser, as the other source guards read the files,
 * so a mock written in a comment is no mock.
 */
import fs from "fs";
import path from "path";
import ts from "typescript";

const SRC = path.resolve(__dirname, "..");

const relative = (file: string) => path.relative(SRC, file).split(path.sep).join("/");

/** Every TypeScript and JavaScript file under src/ that calls jest.mock, this one left out. */
function mockingFiles(dir: string = SRC): string[] {
  const files: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...mockingFiles(full));
    else if (/\.[jt]sx?$/.test(entry.name) && full !== __filename && /jest\.(do)?[mM]ock\(/.test(fs.readFileSync(full, "utf8"))) {
      files.push(full);
    }
  }
  return files;
}

type Mock = { module: string; virtual: boolean; at: string };

/** The module a mock names: a package's specifier, or a relative one's path under src/ without its extension. */
function moduleOf(file: string, specifier: string): string {
  if (!specifier.startsWith(".")) return specifier;
  return relative(path.resolve(path.dirname(file), specifier)).replace(/\.[jt]sx?$/, "");
}

/** The `jest.mock` and `jest.doMock` calls of *text*, the file *file*. */
function mocksOf(file: string, text: string): Mock[] {
  const kind = /\.[jt]sx$/.test(file) ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const mocks: Mock[] = [];
  const visit = (node: ts.Node): void => {
    if (
      ts.isCallExpression(node)
      && ts.isPropertyAccessExpression(node.expression)
      && ts.isIdentifier(node.expression.expression)
      && node.expression.expression.text === "jest"
      && ["mock", "doMock"].includes(node.expression.name.text)
    ) {
      const [specifier, , options] = node.arguments;
      if (specifier && ts.isStringLiteralLike(specifier)) {
        const virtual = options !== undefined && ts.isObjectLiteralExpression(options) && options.properties.some(
          (property) => ts.isPropertyAssignment(property)
            && (ts.isIdentifier(property.name) || ts.isStringLiteral(property.name))
            && property.name.text === "virtual"
            && property.initializer.kind === ts.SyntaxKind.TrueKeyword,
        );
        const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
        mocks.push({ module: moduleOf(file, specifier.text), virtual, at: `${relative(file)}:${line}` });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return mocks;
}

/** Each module mocked both ways, with the mocks of the rarer way: both ways' on a tie. */
function mixedModules(mocks: Mock[]): string[] {
  const byModule = new Map<string, { virtual: string[]; plain: string[] }>();
  for (const mock of mocks) {
    const ways = byModule.get(mock.module) ?? { virtual: [], plain: [] };
    ways[mock.virtual ? "virtual" : "plain"].push(mock.at);
    byModule.set(mock.module, ways);
  }
  const mixed: string[] = [];
  for (const [module, { virtual, plain }] of [...byModule].sort(([a], [b]) => a.localeCompare(b))) {
    if (virtual.length === 0 || plain.length === 0) continue;
    const odd = [
      ...(virtual.length <= plain.length ? [`virtual in ${virtual.join(", ")}`] : []),
      ...(plain.length <= virtual.length ? [`plain in ${plain.join(", ")}`] : []),
    ];
    mixed.push(`${module} (${virtual.length} virtual, ${plain.length} plain): ${odd.join("; ")}`);
  }
  return mixed;
}

describe("every module the suites mock is mocked one way", () => {
  const mocks = mockingFiles().flatMap((file) => mocksOf(file, fs.readFileSync(file, "utf8")));

  test("reads the mocks of the suites and of their support modules", () => {
    // A guard on the guard: with the walk cut short, the rule below would pass.
    expect(mocks.length).toBeGreaterThan(1000);
    const modules = new Set(mocks.map((mock) => mock.module));
    for (const module of ["@urban-toolkit/autk-db", "@urban-toolkit/autk-compute", "vega", "providers/FlowProvider"]) {
      expect(modules).toContain(module);
    }
    expect(mocks.some((mock) => mock.at.startsWith("tests/adapters/node/autkPointSize.test.ts:"))).toBe(true);
  });

  test("tells a virtual mock from a plain one, and names a relative module by its path", () => {
    const probe = [
      '// jest.mock("@urban-toolkit/autk-db", () => ({}), { virtual: true }); in a comment is no mock',
      'jest.mock("@urban-toolkit/autk-db", () => ({}));',
      "jest.mock('@urban-toolkit/autk-map', () => ({}), { virtual: true });",
      'jest.doMock("@urban-toolkit/autk-plot", () => ({}), { "virtual": true });',
      'jest.mock("@urban-toolkit/autk-core", () => ({}), { virtual: false });',
      "jest.mock(`@urban-toolkit/autk-compute`, () => ({ ComputeGpgpu: jest.fn() }), {",
      "  virtual: true,",
      "});",
      "jest.mock('../../providers/FlowProvider', () => ({}));",
    ].join("\n");
    expect(mocksOf(path.join(SRC, "tests/parity/probe.ts"), probe)).toEqual([
      { module: "@urban-toolkit/autk-db", virtual: false, at: "tests/parity/probe.ts:2" },
      { module: "@urban-toolkit/autk-map", virtual: true, at: "tests/parity/probe.ts:3" },
      { module: "@urban-toolkit/autk-plot", virtual: true, at: "tests/parity/probe.ts:4" },
      { module: "@urban-toolkit/autk-core", virtual: false, at: "tests/parity/probe.ts:5" },
      { module: "@urban-toolkit/autk-compute", virtual: true, at: "tests/parity/probe.ts:6" },
      { module: "providers/FlowProvider", virtual: false, at: "tests/parity/probe.ts:9" },
    ]);
  });

  test("names the mocks of the rarer way", () => {
    const mock = (module: string, virtual: boolean, at: string): Mock => ({ module, virtual, at });
    expect(mixedModules([
      mock("a", true, "x.test.ts:1"), mock("a", true, "y.test.ts:1"), mock("a", false, "z.test.ts:1"),
      mock("b", true, "x.test.ts:2"), mock("b", false, "y.test.ts:2"),
      mock("c", false, "x.test.ts:3"), mock("c", false, "y.test.ts:3"),
    ])).toEqual([
      "a (2 virtual, 1 plain): plain in z.test.ts:1",
      "b (1 virtual, 1 plain): virtual in x.test.ts:2; plain in y.test.ts:2",
    ]);
  });

  test("no module is mocked virtually in one file and plainly in another", () => {
    expect(mixedModules(mocks)).toEqual([]);
  });
});
