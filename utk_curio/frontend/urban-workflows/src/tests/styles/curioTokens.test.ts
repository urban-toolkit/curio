import fs from "fs";
import path from "path";

/**
 * Every `var(--curio-…)` referenced under src/ must be declared somewhere.
 *
 * The bug this exists for: `PackageMetadataModal.module.css` painted its
 * primary button with `background: var(--curio-accent)` and
 * `color: var(--curio-on-accent)`, neither of which was ever declared. An
 * undeclared custom property makes the declaration invalid at computed-value
 * time, so the button rendered with a transparent background and inherited
 * text — visually identical to the Cancel button beside it. Nothing failed;
 * the modal just quietly lost its primary action.
 *
 * A reference with a fallback (`var(--x, #fff)`) still counts as a reference:
 * the fallback keeps the page working, but a token that only ever resolves
 * through its fallback is a token that does not exist, and the next author to
 * change the "real" value in curioTokens.css will find it has no effect.
 */

const SRC = path.resolve(__dirname, "../..");
const TOKENS_CSS = path.join(SRC, "styles", "curioTokens.css");

const EXTENSIONS = new Set([".css", ".ts", ".tsx"]);

/**
 * Skipped when collecting references.
 *
 * `tests` because a test may name a token in prose — this file's own docstring
 * cites the two that caused the bug. `jestMocks` because a fixture is allowed
 * to reference something that does not exist.
 */
const SKIP_DIRS = new Set(["tests", "jestMocks"]);

function walk(dir: string, out: string[] = [], skip = true): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!skip || !SKIP_DIRS.has(entry.name)) walk(path.join(dir, entry.name), out, skip);
    } else if (EXTENSIONS.has(path.extname(entry.name))) {
      out.push(path.join(dir, entry.name));
    }
  }
  return out;
}

const DECLARATION = /(--curio-[a-z0-9-]+)\s*:/g;

/** Tokens declared in curioTokens.css — the palette proper. */
function globalTokens(): Set<string> {
  const css = fs.readFileSync(TOKENS_CSS, "utf8");
  const names = new Set<string>();
  const re = /^\s*(--curio-[a-z0-9-]+)\s*:/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css)) !== null) names.add(m[1]);
  return names;
}

/**
 * Tokens a component declares for itself — e.g. `--curio-drawer-z`, which each
 * catalog drawer sets to its own tier so the shared shell can read one name.
 * Legitimate, and not part of the palette.
 */
function localTokens(): Set<string> {
  const names = new Set<string>();
  for (const file of walk(SRC, [], false)) {
    if (file === TOKENS_CSS) continue;
    const body = fs.readFileSync(file, "utf8");
    let m: RegExpExecArray | null;
    const re = new RegExp(DECLARATION.source, "g");
    while ((m = re.exec(body)) !== null) names.add(m[1]);
  }
  return names;
}

/** Every referenced token, mapped to the files that reference it. */
function referencedTokens(includeTokensFile: boolean): Map<string, string[]> {
  const refs = new Map<string, string[]>();
  const files = walk(SRC);
  for (const file of files) {
    if (file === TOKENS_CSS && !includeTokensFile) continue;
    const body = fs.readFileSync(file, "utf8");
    const re = /var\(\s*(--curio-[a-z0-9-]+)/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(body)) !== null) {
      // Count only a well-formed reference: the name, then either the closing
      // paren or a fallback. That excludes the two things that otherwise read
      // as a token name and are not one — a reference built at runtime
      // (`var(--curio-category-${key}-fg)`) and a family named in a comment
      // (`var(--curio-category-*)`).
      const close = body.indexOf(")", m.index);
      if (close === -1) continue;
      const rest = body.slice(m.index + m[0].length, close).trim();
      if (rest !== "" && !rest.startsWith(",")) continue;
      const rel = path.relative(SRC, file).replace(/\\/g, "/");
      const seen = refs.get(m[1]);
      if (seen) {
        if (!seen.includes(rel)) seen.push(rel);
      } else {
        refs.set(m[1], [rel]);
      }
    }
  }
  return refs;
}

/**
 * Token families resolved dynamically, so no file names them in full.
 *
 * `--curio-format-*` and `--curio-category-*` are looked up by key at runtime
 * (`var(--curio-category-${key}-fg)`), which is the whole point of keying a
 * colour off a dataset's format or a package's category. Their completeness is
 * guarded separately by tests/catalog/datasetFormatStyles.test.ts and
 * tests/styles/nodeCategoryPalette.test.ts.
 */
const DYNAMIC_FAMILIES = [/^--curio-format-/, /^--curio-category-/];

describe("curio design tokens", () => {
  const global = globalTokens();
  const local = localTokens();
  const referenced = referencedTokens(false);
  const referencedAnywhere = referencedTokens(true);

  it("parses a healthy number of tokens", () => {
    // A guard on the guard: if either regex silently stops matching, every
    // assertion below passes vacuously.
    expect(global.size).toBeGreaterThan(50);
    expect(referenced.size).toBeGreaterThan(20);
  });

  it("declares every token that any file references", () => {
    const missing = [...referenced.entries()]
      .filter(([name]) => !global.has(name) && !local.has(name))
      .map(([name, files]) => `${name}  (referenced by ${files.join(", ")})`);

    expect(missing).toEqual([]);
  });

  it("references every token it declares", () => {
    // A token nothing reads is either a leftover or a rename that landed on
    // only one side. A reference from inside curioTokens.css counts: the role
    // aliases (--curio-role-update-fg and friends) point at the raw accent
    // palette on purpose, so that the meaning can be renamed without moving
    // the colour.
    const unused = [...global].filter(
      (name) =>
        !referencedAnywhere.has(name) && !DYNAMIC_FAMILIES.some((re) => re.test(name))
    );
    expect(unused).toEqual([]);
  });
});
