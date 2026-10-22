/**
 * Every hover in Curio is the one Curio tooltip (components/tooltip): text in
 * a `data-tooltip` attribute, or content a target registers with
 * useTooltipContent, drawn by the one TooltipLayer on document.body. Nothing
 * else may draw one:
 *
 * - a `title` on an element, which the browser shows as its own grey box,
 *   after about a second and never on keyboard focus or touch. That covers
 *   react-flow's Handle, which hands its props to a div; FontAwesomeIcon, which
 *   turns a `title` into an SVG <title>, shown the same way; an SVG <title>
 *   written out; and a title set with setAttribute. A component's own `title`
 *   prop (a dialog's heading, a tab's label) is its own business;
 * - react-bootstrap's OverlayTrigger and Tooltip, and MUI's Tooltip;
 * - a Monaco decoration's hoverMessage, and an editor whose own hover is on.
 *   Monaco draws its hovers inside the node, so the canvas's zoom scales them
 *   and the card clips them.
 *
 * Read with the TypeScript parser, as the other source guards read the files
 * with patterns, so a comment or a string that names one of these is no use
 * of it.
 */
import fs from "fs";
import path from "path";
import ts from "typescript";

const SRC = path.resolve(__dirname, "../../..");

/**
 * What the guard does not read yet, each with its reason: a folder or a file
 * under src/.
 */
const EXCEPTIONS: ReadonlyArray<{ what: string; under: string; reason: string }> = [];

/** The editors the app mounts, each of which has to turn Monaco's hover off. */
const EDITORS = ["components/editing/CodeEditor.tsx", "components/editing/GrammarEditor.tsx"];

/** Components that hand a `title` to the page as a native one: [module, export]. */
const NATIVE_TITLE_COMPONENTS: Array<[string, string]> = [
  ["reactflow", "Handle"],
  ["@reactflow/core", "Handle"],
  ["@fortawesome/react-fontawesome", "FontAwesomeIcon"],
];

/** Other tooltips, which may not be imported: [module, export], "default" for a default import. */
const OTHER_TOOLTIPS: Array<[string, string]> = [
  ["react-bootstrap", "OverlayTrigger"],
  ["react-bootstrap", "Tooltip"],
  ["react-bootstrap/OverlayTrigger", "default"],
  ["react-bootstrap/Tooltip", "default"],
  ["@mui/material", "Tooltip"],
  ["@mui/material/Tooltip", "default"],
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

const excepted = (file: string) => EXCEPTIONS.some((exception) => relative(file).startsWith(exception.under));

function parse(file: string, text: string): ts.SourceFile {
  const kind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  return ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
}

/** The names *source*'s imports give *exported* of *module* ("default" for its default export). */
function localNames(source: ts.SourceFile, module: string, exported: string): string[] {
  const names: string[] = [];
  for (const statement of source.statements) {
    if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) continue;
    if (statement.moduleSpecifier.text !== module || !statement.importClause) continue;
    const clause = statement.importClause;
    if (exported === "default" && clause.name) names.push(clause.name.text);
    if (clause.namedBindings && ts.isNamedImports(clause.namedBindings)) {
      for (const element of clause.namedBindings.elements) {
        if ((element.propertyName ?? element.name).text === exported) names.push(element.name.text);
      }
    }
  }
  return names;
}

/** An element the page draws as it is written (`div`, `button`, `svg:title`), not a component. */
const intrinsic = (tag: ts.JsxTagNameExpression) =>
  (ts.isIdentifier(tag) && /^[a-z]/.test(tag.text)) || ts.isJsxNamespacedName(tag);

interface Finding {
  rule: "title" | "import" | "hoverMessage";
  at: string;
}

/** Each title, other tooltip and hoverMessage in *text*, the file *file*. */
function findings(file: string, text: string): Finding[] {
  const source = parse(file, text);
  const out: Finding[] = [];
  const at = (node: ts.Node) =>
    `${relative(file)}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1}: ` +
    node.getText(source).split("\n")[0].slice(0, 120);

  for (const [module, exported] of OTHER_TOOLTIPS) {
    for (const name of localNames(source, module, exported)) {
      out.push({ rule: "import", at: `${relative(file)}: ${name}, ${exported} of ${module}` });
    }
  }
  const titleToPage = new Set(NATIVE_TITLE_COMPONENTS.flatMap(([module, exported]) => localNames(source, module, exported)));

  const visit = (node: ts.Node): void => {
    if (ts.isJsxAttribute(node) && node.name.getText(source) === "title") {
      const tag = node.parent.parent.tagName;
      if (intrinsic(tag) || (ts.isIdentifier(tag) && titleToPage.has(tag.text))) out.push({ rule: "title", at: at(node) });
    }
    if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && ts.isIdentifier(node.tagName) && node.tagName.text === "title") {
      out.push({ rule: "title", at: at(node) });
    }
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      node.expression.name.text === "setAttribute" &&
      node.arguments.length > 0 &&
      ts.isStringLiteralLike(node.arguments[0]) &&
      node.arguments[0].text === "title"
    ) {
      out.push({ rule: "title", at: at(node) });
    }
    if ((ts.isIdentifier(node) || ts.isStringLiteralLike(node)) && node.text === "hoverMessage") {
      out.push({ rule: "hoverMessage", at: at(node) });
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return out;
}

/** The Monaco editors *text* renders, and how many of them turn Monaco's own hover off in their own options. */
function editorHovers(file: string, text: string): { editors: number; hoverOff: number } {
  const source = parse(file, text);
  const names = new Set([
    ...localNames(source, "@monaco-editor/react", "default"),
    ...localNames(source, "@monaco-editor/react", "Editor"),
  ]);
  const property = (object: ts.ObjectLiteralExpression, name: string) =>
    object.properties.find(
      (p): p is ts.PropertyAssignment => ts.isPropertyAssignment(p) && p.name.getText(source) === name,
    );
  let editors = 0;
  let hoverOff = 0;
  const visit = (node: ts.Node): void => {
    if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && ts.isIdentifier(node.tagName) && names.has(node.tagName.text)) {
      editors += 1;
      const options = node.attributes.properties.find(
        (a): a is ts.JsxAttribute => ts.isJsxAttribute(a) && a.name.getText(source) === "options",
      );
      const value = options?.initializer && ts.isJsxExpression(options.initializer) ? options.initializer.expression : undefined;
      const hover = value && ts.isObjectLiteralExpression(value) ? property(value, "hover") : undefined;
      const enabled = hover && ts.isObjectLiteralExpression(hover.initializer) ? property(hover.initializer, "enabled") : undefined;
      if (enabled?.initializer.kind === ts.SyntaxKind.FalseKeyword) hoverOff += 1;
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return { editors, hoverOff };
}

describe("no hover but the one Curio tooltip", () => {
  const files = sourceFiles().filter((file) => !excepted(file));
  const read = (file: string) => fs.readFileSync(file, "utf8");
  const found = files.flatMap((file) => findings(file, read(file)));
  const of = (rule: Finding["rule"]) => found.filter((finding) => finding.rule === rule).map((finding) => finding.at);

  test("reads the app's code, its editors among it", () => {
    // A guard on the guard: if the walk stopped short, every rule below would pass.
    expect(files.length).toBeGreaterThan(300);
    expect(files.map(relative)).toEqual(expect.arrayContaining(EDITORS));
  });

  test("finds each kind of hover it forbids, and nothing else", () => {
    const probe = [
      'import { OverlayTrigger, Tooltip as Tip } from "react-bootstrap";',
      'import Overlay from "react-bootstrap/OverlayTrigger";',
      'import { Tooltip } from "@mui/material";',
      'import { Handle as Port } from "reactflow";',
      'import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";',
      "// title=\"Delete node\" and hoverMessage, named in a comment, are no use of either",
      'const button = <button title="Delete node" />;',
      'const port = <Port title="input_0" />;',
      'const icon = <FontAwesomeIcon icon={faPlay} title="Run" />;',
      "const map = <svg><title>Map</title></svg>;",
      'const chip = { hoverMessage: { value: "season" } };',
      'el.setAttribute("title", "Delete node");',
      'const dialog = <ConfirmDialog title="Delete it?" />;',
      'const tab = <Tab title="Code" />;',
      'const label = "title=";',
    ].join("\n");
    const rules = findings(path.join(SRC, "probe.tsx"), probe).map((finding) => finding.rule);
    expect({
      import: rules.filter((rule) => rule === "import").length,
      title: rules.filter((rule) => rule === "title").length,
      hoverMessage: rules.filter((rule) => rule === "hoverMessage").length,
    }).toEqual({ import: 4, title: 5, hoverMessage: 1 });

    const editors = [
      'import Editor from "@monaco-editor/react";',
      "const on = <Editor options={{ fontSize: 13, ...look.editorOptions }} />;",
      "const off = <Editor options={{ fontSize: 13, hover: { enabled: false } }} />;",
    ].join("\n");
    expect(editorHovers(path.join(SRC, "probe.tsx"), editors)).toEqual({ editors: 2, hoverOff: 1 });
  });

  test("no element carries a native title", () => {
    expect(of("title")).toEqual([]);
  });

  test("no other tooltip is imported", () => {
    expect(of("import")).toEqual([]);
  });

  test("no Monaco decoration carries a hoverMessage", () => {
    expect(of("hoverMessage")).toEqual([]);
  });

  test("every Monaco editor turns its own hover off, in its own options", () => {
    const editors = files
      .filter((file) => read(file).includes("@monaco-editor/react"))
      .map((file) => ({ file: relative(file), ...editorHovers(file, read(file)) }))
      .filter((editor) => editor.editors > 0);
    expect(editors.map((editor) => editor.file)).toEqual(expect.arrayContaining(EDITORS));
    expect(editors.filter((editor) => editor.hoverOff < editor.editors).map((editor) => editor.file)).toEqual([]);
  });

  test("each exception names files that are there, and says why", () => {
    for (const exception of EXCEPTIONS) {
      expect({ under: exception.under, there: fs.existsSync(path.join(SRC, exception.under)) }).toEqual({
        under: exception.under,
        there: true,
      });
      expect(exception.reason).not.toBe("");
    }
  });
});
