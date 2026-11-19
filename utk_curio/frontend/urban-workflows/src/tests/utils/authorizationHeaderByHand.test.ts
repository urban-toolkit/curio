/**
 * Every request a page sends with its sign-in names the dataflow the page
 * shows: the one helper that writes the sign-in's header,
 * `utils/requestHeaders.ts`, writes the dataflow's beside it. With several
 * backend processes, the router sends each request to the process that owns
 * that dataflow, and a request that names none to the home process. A client
 * that wrote its own `Authorization` header would send the sign-in without
 * the dataflow, so no module of the frontend but the helper writes that
 * header or a bearer token.
 *
 * Read with the TypeScript parser, as the other source guards read the files
 * with patterns, so a comment or a sentence that names the header is no use
 * of it.
 */
import fs from "fs";
import path from "path";
import ts from "typescript";

const SRC = path.resolve(__dirname, "../..");
const HELPER = "utils/requestHeaders.ts";

/** The clients that send the sign-in: the guard reads each of them. */
const CLIENTS = [
  "utils/authApi.ts",
  "utils/sseStream.ts",
  "utils/nodeRunRequest.ts",
  "utils/useAuthedObjectUrl.ts",
  "services/api.ts",
  "services/outputFiles.ts",
  "services/nodeRuntimeReport.ts",
  "services/datasetCatalog/datasetCatalogApi.ts",
  "services/packages/packagesBlobTransport.ts",
  "services/agents/skillsApi.ts",
  "registry/packagesClient.ts",
  "providers/starters.ts",
  "components/nodes/NodeOutcomeStrip.tsx",
];

const relative = (file: string) => path.relative(SRC, file).split(path.sep).join("/");

/** Every TypeScript file under src/, the tests, the Jest mocks and type declarations left out. */
function sourceFiles(dir: string = SRC): string[] {
  const files: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (full !== path.join(SRC, "tests") && entry.name !== "jestMocks") files.push(...sourceFiles(full));
    } else if (/\.tsx?$/.test(entry.name) && !/\.(test|spec)\.tsx?$/.test(entry.name) && !entry.name.endsWith(".d.ts")) {
      files.push(full);
    }
  }
  return files;
}

/** Each place *text*, the file *file*, writes the sign-in's header or a bearer token. */
function findings(file: string, text: string): string[] {
  const kind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const out: string[] = [];
  const at = (node: ts.Node) =>
    `${relative(file)}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1}: ` +
    node.getText(source).split("\n")[0].slice(0, 120);
  const visit = (node: ts.Node): void => {
    // `{ Authorization: ... }`, `headers.Authorization = ...`, `{ Authorization }`.
    if (ts.isIdentifier(node) && node.text === "Authorization") out.push(at(node));
    // `headers["Authorization"]`, `{ "authorization": ... }`, `headers.set("Authorization", ...)`.
    if (ts.isStringLiteralLike(node) && node.text.toLowerCase() === "authorization") out.push(at(node));
    // `Bearer ${token}`, as a template or a string.
    if ((ts.isStringLiteralLike(node) || ts.isTemplateHead(node)) && /^bearer /i.test(node.text)) out.push(at(node));
    ts.forEachChild(node, visit);
  };
  visit(source);
  return out;
}

describe("no request writes the sign-in's header but through the one helper", () => {
  const files = sourceFiles();
  const read = (file: string) => fs.readFileSync(file, "utf8");

  test("reads the app's code, every client that sends the sign-in among it", () => {
    // A guard on the guard: if the walk stopped short, the rule below would pass.
    expect(files.length).toBeGreaterThan(300);
    expect(files.map(relative)).toEqual(expect.arrayContaining(CLIENTS));
  });

  test("finds each way of writing the header, and nothing else", () => {
    const probe = [
      "// Authorization: Bearer, named in a comment, is no use of either",
      "const a = { Authorization: `Bearer ${token}` };",
      "const b = { 'Authorization': token };",
      "headers['Authorization'] = token;",
      "headers.Authorization = token;",
      "const c = { Authorization };",
      "init.headers.set('authorization', token);",
      "const d = 'Bearer ' + token;",
      'const refusal = "Authorization required.";',
      'const credential = "(?:Bearer\\\\s+)?[A-Za-z0-9]";',
      "const socket = io(url, { auth: { token } });",
      "const asks = !!getToken();",
      "const kind = response.headers.get('Content-Type');",
    ].join("\n");
    // Seven lines write it; the comment, the sentence, the pattern and the
    // rest do not. The first line writes it twice: its key and its token.
    expect(findings(path.join(SRC, "probe.ts"), probe).map((finding) => finding.split(":")[1])).toEqual([
      "2", "2", "3", "4", "5", "6", "7", "8",
    ]);
  });

  test("no module but the helper writes it", () => {
    const writes = files.filter((file) => relative(file) !== HELPER).flatMap((file) => findings(file, read(file)));
    expect(writes).toEqual([]);
  });

  test("the helper writes it, beside the dataflow the page shows", () => {
    const helper = path.join(SRC, HELPER);
    expect(fs.existsSync(helper)).toBe(true);
    const text = read(helper);
    expect(findings(helper, text).length).toBeGreaterThan(0);
    expect(text).toContain("DATAFLOW_HEADER");
  });
});
