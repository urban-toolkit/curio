/**
 * The guides name SCOUT's raster package, Rasterization
 * (`curio.rasterization@1`), and the Vega-Lite package (`curio.vega-lite@1`),
 * the two packages Scout became, one by what each node does, and never a
 * package they replaced: Scout, nor the two Scout replaced, SCOUT Rasters
 * (`scout.rasters@1`) and SCOUT Comparison (`scout.comparison@1`), each
 * retired with no alias. Neither do the workflows nor the pages at the
 * repository's root.
 *
 * The guides are read from the checkout. The backend suite runs in the CI
 * image, which ships no guides and no workflows, so this check lives here;
 * the files Curio ships are `test_rasterization_package.py`'s.
 */
import * as fs from "fs";
import * as path from "path";

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..");
const DOCS = path.join(REPO_ROOT, "docs");

/** Either retired id as a whole id; the module `scout_rasters` keeps its name. */
const RETIRED_ID = /(?<![\w.-])scout\.(?:rasters|comparison)(?![\w-])/g;
/** Scout's id as a whole id: its package's, or the package of a node type. */
const SCOUT_ID = /(?<![\w.-])curio\.scout(?![\w-])/g;

function readGuides(): Array<[string, string]> {
    return fs.readdirSync(DOCS)
        .filter((name) => name.endsWith(".md"))
        .sort()
        .map((name): [string, string] => [name, fs.readFileSync(path.join(DOCS, name), "utf-8")]);
}

/** Each file under *dir*, from the repository's root, and its text. */
function readTree(dir: string): Array<[string, string]> {
    return fs.readdirSync(path.join(REPO_ROOT, dir), { withFileTypes: true })
        .sort((a, b) => a.name.localeCompare(b.name))
        .flatMap((entry): Array<[string, string]> => {
            const relative = path.join(dir, entry.name);
            if (entry.isDirectory()) return readTree(relative);
            return [[relative, fs.readFileSync(path.join(REPO_ROOT, relative), "utf-8")]];
        });
}

function named(files: Array<[string, string]>, id: RegExp): string[] {
    return files.flatMap(([name, text]) =>
        text.split("\n").flatMap((line, index) =>
            Array.from(line.matchAll(id), (match) => `${name}:${index + 1}: ${match[0]}`),
        ),
    );
}

test("no guide names a retired SCOUT package or its node types", () => {
    const guides = readGuides();
    // Finding next to no guides means the folder moved, not that all is well.
    expect(guides.length).toBeGreaterThan(10);
    expect(named(guides, RETIRED_ID)).toEqual([]);
});

test("no guide, workflow or page at the root names Scout's package or its node types", () => {
    const guides = readGuides();
    expect(guides.length).toBeGreaterThan(10);
    const workflows = readTree(".github");
    expect(workflows.length).toBeGreaterThan(5);
    const pages = fs.readdirSync(REPO_ROOT)
        .filter((name) => name.endsWith(".md"))
        .sort()
        .map((name): [string, string] => [name, fs.readFileSync(path.join(REPO_ROOT, name), "utf-8")]);
    expect(pages.map(([name]) => name)).toEqual(expect.arrayContaining(["AGENTS.md", "README.md"]));
    expect(named([...guides, ...workflows, ...pages], SCOUT_ID)).toEqual([]);
});

test("the Node Catalog guide lists Rasterization and the Vega-Lite package among the packages Curio ships", () => {
    const guide = fs.readFileSync(path.join(DOCS, "NODE-CATALOG.md"), "utf-8");
    for (const [dirName, name] of [["curio.rasterization@1", "Rasterization"], ["curio.vega-lite@1", "Vega-Lite"]]) {
        const rows = guide.split("\n").filter((line) => line.startsWith(`| \`${dirName}\` |`));
        expect(rows).toHaveLength(1);
        expect(rows[0]).toContain(`| ${name}`);
        expect(rows[0]).toContain(`packages/${dirName}/README.md`);
    }
});
