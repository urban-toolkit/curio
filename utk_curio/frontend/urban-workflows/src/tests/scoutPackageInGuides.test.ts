/**
 * The guides name SCOUT's raster package, Scout (`curio.scout@1`), and never
 * the two it replaced: SCOUT Rasters (`scout.rasters@1`) and SCOUT Comparison
 * (`scout.comparison@1`), retired with no alias (the plan answering komar41's
 * review of his #914, step 10). Nor do they name a Scout chart type: a chart
 * that compares scenarios is a Vega-Lite node (#1270).
 *
 * The guides are read from the checkout. The backend suite runs in the CI
 * image, which ships no guides, so this check lives here; the files Curio
 * ships are `test_scout_package.py`'s.
 */
import * as fs from "fs";
import * as path from "path";

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..");
const DOCS = path.join(REPO_ROOT, "docs");

/** Either retired id as a whole id; the module `scout_rasters` keeps its name. */
const RETIRED_ID = /(?<![\w.-])scout\.(?:rasters|comparison)(?![\w-])/g;

/** A Scout chart type as a whole type, such as `curio.scout/bars`: one of the
 *  fifteen charts' ids of `docs/examples/vega-lite-charts` under Scout's. */
function scoutChartType(): RegExp {
    const listed = JSON.parse(
        fs.readFileSync(path.join(DOCS, "examples", "vega-lite-charts", "charts.json"), "utf-8"),
    );
    const ids: string[] = listed.charts.map((chart: { id: string }) => chart.id);
    expect(ids).toHaveLength(15);
    const names = [...ids].sort((a, b) => b.length - a.length).join("|");
    return new RegExp(`(?<![\\w.-])curio\\.scout/(?:${names})(?![\\w-])`, "g");
}

function readGuides(): Array<[string, string]> {
    return fs.readdirSync(DOCS)
        .filter((name) => name.endsWith(".md"))
        .sort()
        .map((name): [string, string] => [name, fs.readFileSync(path.join(DOCS, name), "utf-8")]);
}

test("no guide names a retired SCOUT package or its node types", () => {
    const guides = readGuides();
    // Finding next to no guides means the folder moved, not that all is well.
    expect(guides.length).toBeGreaterThan(10);
    const named = guides.flatMap(([name, text]) =>
        text.split("\n").flatMap((line, index) =>
            Array.from(line.matchAll(RETIRED_ID), (match) => `${name}:${index + 1}: ${match[0]}`),
        ),
    );
    expect(named).toEqual([]);
});

test("no guide names a Scout chart type", () => {
    const guides = readGuides();
    expect(guides.length).toBeGreaterThan(10);
    const chartType = scoutChartType();
    const named = guides.flatMap(([name, text]) =>
        text.split("\n").flatMap((line, index) =>
            Array.from(line.matchAll(chartType), (match) => `${name}:${index + 1}: ${match[0]}`),
        ),
    );
    expect(named).toEqual([]);
});

test("the Node Catalog guide lists Scout among the packages Curio ships", () => {
    const guide = fs.readFileSync(path.join(DOCS, "NODE-CATALOG.md"), "utf-8");
    const rows = guide.split("\n").filter((line) => line.startsWith("| `curio.scout@1` |"));
    expect(rows).toHaveLength(1);
    expect(rows[0]).toContain("| Scout");
    expect(rows[0]).toContain("packages/curio.scout@1/README.md");
});
