/**
 * Every suite that loads autk-grammar's build, the CommonJS file of the
 * grammar the app bundles, mocks the packages the build requires plainly,
 * never as virtual mocks. autkPointSize.test.ts requires the build, and the
 * camera suites read its `applyCamera` through _support/autkApplyCamera.
 *
 * A Jest worker keeps one resolver for every file it runs, and the resolver
 * keeps the module id it first worked out for a file's require of a name:
 * under a virtual mock that id is the package's name, under a plain one the
 * package's installed file. When one suite that loads the build mocks a
 * package virtually and another plainly, the build's require in whichever of
 * the two runs second in a worker finds the other's id, which none of its own
 * mocks is under, and loads the installed package, an ES module Jest cannot
 * read: "Cannot use import statement outside a module", in
 * autkPointSize.test.ts (run 44339134488) or in autkNodeCamera.test.tsx
 * (run 44341322614), as the order fell.
 *
 * Read with the TypeScript parser, as the other source guards read the files,
 * so a mock written in a comment is no mock.
 */
import fs from "fs";
import path from "path";
import ts from "typescript";

const TESTS = path.resolve(__dirname, "../..");
/** The build, as a suite names it. */
const BUILD_PATH = "autk-grammar/dist/autk-grammar.umd.cjs";
const BUILD = path.resolve(TESTS, "../../node_modules/@urban-toolkit", BUILD_PATH);

const relative = (file: string) => path.relative(TESTS, file).split(path.sep).join("/");

/** The packages the build requires: the `require` calls of its CommonJS branch. */
function buildRequires(): string[] {
  const text = fs.readFileSync(BUILD, "utf8");
  const commonJs = text.slice(0, text.indexOf("define("));
  return [...commonJs.matchAll(/require\("([^"]+)"\)/g)].map((match) => match[1]);
}

/** Every TypeScript file under src/tests, this one left out. */
function testFiles(dir: string = TESTS): string[] {
  const files: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...testFiles(full));
    else if (/\.tsx?$/.test(entry.name) && full !== __filename) files.push(full);
  }
  return files;
}

type Mock = { name: string; virtual: boolean; at: string };

/** The `jest.mock` and `jest.doMock` calls of *text*, the file *file*, each with whether it is virtual. */
function mocksOf(file: string, text: string): Mock[] {
  const kind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const mocks: Mock[] = [];
  const visit = (node: ts.Node): void => {
    if (
      ts.isCallExpression(node)
      && ts.isPropertyAccessExpression(node.expression)
      && ts.isIdentifier(node.expression.expression)
      && node.expression.expression.text === "jest"
      && ["mock", "doMock"].includes(node.expression.name.text)
      && node.arguments.length > 0
      && ts.isStringLiteralLike(node.arguments[0])
    ) {
      const options = node.arguments[2];
      const virtual = options !== undefined && ts.isObjectLiteralExpression(options) && options.properties.some(
        (property) => ts.isPropertyAssignment(property)
          && (ts.isIdentifier(property.name) || ts.isStringLiteral(property.name))
          && property.name.text === "virtual"
          && property.initializer.kind === ts.SyntaxKind.TrueKeyword,
      );
      const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
      mocks.push({ name: node.arguments[0].text, virtual, at: `${relative(file)}:${line}` });
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return mocks;
}

describe("the suites that load autk-grammar's build mock its packages plainly", () => {
  const texts = new Map<string, string>();
  const read = (file: string): string => {
    if (!texts.has(file)) texts.set(file, fs.readFileSync(file, "utf8"));
    return texts.get(file)!;
  };
  const files = testFiles();
  // The support modules that load the build, and the files that load it: by
  // its path, or through one of those modules.
  const supports = files
    .filter((file) => relative(file).startsWith("_support/") && read(file).includes(BUILD_PATH))
    .map((file) => relative(file).replace(/\.tsx?$/, ""));
  const loaders = files.filter((file) => read(file).includes(BUILD_PATH)
    || supports.some((support) => new RegExp(`["'](?:\\.\\.?/)+${support}["']`).test(read(file))));
  const packages = buildRequires();

  test("reads the packages the build requires and the suites that load it", () => {
    // A guard on the guard: with no package or no suite read, the rule below would pass.
    expect(packages).toEqual(expect.arrayContaining(["@urban-toolkit/autk-db", "@urban-toolkit/autk-core"]));
    expect(supports).toEqual(expect.arrayContaining(["_support/autkApplyCamera"]));
    expect(loaders.map(relative)).toEqual(expect.arrayContaining([
      "adapters/node/autkPointSize.test.ts",
      "adapters/node/autkMapCamera.test.ts",
      "adapters/node/autkNodeCamera.test.tsx",
    ]));
  });

  test("tells a virtual mock from a plain one", () => {
    const probe = [
      '// jest.mock("@urban-toolkit/autk-db", () => ({}), { virtual: true }); in a comment is no mock',
      'jest.mock("@urban-toolkit/autk-db", () => ({}));',
      "jest.mock('@urban-toolkit/autk-map', () => ({}), { virtual: true });",
      'jest.doMock("@urban-toolkit/autk-plot", () => ({}), { "virtual": true });',
      'jest.mock("@urban-toolkit/autk-core", () => ({}), { virtual: false });',
      "jest.mock(`@urban-toolkit/autk-compute`, () => ({ ComputeGpgpu: jest.fn() }), {",
      "  virtual: true,",
      "});",
    ].join("\n");
    expect(mocksOf(path.join(TESTS, "probe.ts"), probe).map(({ name, virtual, at }) => [name, virtual, at])).toEqual([
      ["@urban-toolkit/autk-db", false, "probe.ts:2"],
      ["@urban-toolkit/autk-map", true, "probe.ts:3"],
      ["@urban-toolkit/autk-plot", true, "probe.ts:4"],
      ["@urban-toolkit/autk-core", false, "probe.ts:5"],
      ["@urban-toolkit/autk-compute", true, "probe.ts:6"],
    ]);
  });

  test("no suite that loads the build mocks one of its packages virtually", () => {
    const virtual = loaders.flatMap((file) => mocksOf(file, read(file))
      .filter((mock) => mock.virtual && packages.includes(mock.name))
      .map((mock) => `${mock.at} ${mock.name}`));
    expect(virtual).toEqual([]);
  });
});
