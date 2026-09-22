/**
 * The Autark data compiler now lives in its own import-free module so two very
 * different callers can share it: the React node behavior, and
 * `scripts/compile-autk-data.mts`, which Node runs directly (type stripping) to
 * give the CI stress harness the exact JavaScript a browser would post.
 *
 * That second caller is the reason for these tests. Nothing in the app imports
 * the module for its own sake, so a change that quietly breaks the pure-module
 * contract -- adding an import, depending on a DOM global, dropping an export --
 * would otherwise only surface as a red stress job much later.
 */
import * as fs from "fs";
import * as path from "path";

import {
    SANDBOX_BACKEND_URL_TOKEN,
    compileDataSpecToAutkDbJs,
    requestedLayerTables,
    resolveDataSourceUrls,
} from "../../../adapters/node/autkDataCompile";

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..", "..", "..");
const EXAMPLES_DIR = path.join(REPO_ROOT, "docs", "examples");
const MODULE_PATH = path.join(
    __dirname, "..", "..", "..", "adapters", "node", "autkDataCompile.ts",
);

function dataSourcesOf(exampleFile: string, nodeId: string): any[] {
    const parsed = JSON.parse(
        fs.readFileSync(path.join(EXAMPLES_DIR, exampleFile), "utf8"),
    );
    const dataflow = parsed?.dataflow ?? parsed;
    const node = (dataflow.nodes ?? []).find((n: any) => n.id === nodeId);
    if (!node) throw new Error(`${exampleFile} has no node ${nodeId}`);
    return JSON.parse(node.content).data;
}

describe("autkDataCompile stays importable outside the browser", () => {
    it("has no imports of its own", () => {
        const source = fs.readFileSync(MODULE_PATH, "utf8");
        // A single import would break `node scripts/compile-autk-data.mts`,
        // which resolves this file with no bundler and no module map.
        expect(source).not.toMatch(/^\s*import\s/m);
        expect(source).not.toMatch(/\brequire\(/);
    });

    it("touches no browser globals", () => {
        const source = fs.readFileSync(MODULE_PATH, "utf8");
        // Property access only: the emitted sandbox code legitimately mentions
        // words like "fetch" in its comments and error strings.
        expect(source).not.toMatch(/\b(window|document|navigator|localStorage)\s*[.[]/);
    });
});

describe("requestedLayerTables", () => {
    it("names one table per auto-loaded OSM layer", () => {
        const sources = dataSourcesOf("11-autark-pbf-loading.json", "pbf-load");
        expect(requestedLayerTables(sources)).toEqual([
            "table_osm_surface",
            "table_osm_parks",
            "table_osm_water",
            "table_osm_roads",
            "table_osm_buildings",
        ]);
    });

    it("ignores join sources, which rewrite a table rather than add one", () => {
        expect(requestedLayerTables([
            { type: "geojson", outputTableName: "zones" },
            { type: "join", outputTableName: "zones" },
        ])).toEqual(["zones"]);
    });
});

describe("resolveDataSourceUrls", () => {
    it("rewrites relative file URLs against the given base", () => {
        const resolved = resolveDataSourceUrls(
            { data: [{ type: "osm", pbfFileUrl: "docs/examples/data/x.osm.pbf" }] },
            SANDBOX_BACKEND_URL_TOKEN,
        );
        expect(resolved.data[0].pbfFileUrl)
            .toBe(`${SANDBOX_BACKEND_URL_TOKEN}/file/docs/examples/data/x.osm.pbf`);
    });

    it("leaves absolute URLs alone", () => {
        const url = "https://example.org/x.geojson";
        const resolved = resolveDataSourceUrls(
            { data: [{ type: "geojson", geojsonFileUrl: url }] },
            SANDBOX_BACKEND_URL_TOKEN,
        );
        expect(resolved.data[0].geojsonFileUrl).toBe(url);
    });
});

describe("compileDataSpecToAutkDbJs", () => {
    const sources = dataSourcesOf("08-autark-spatial-join-regression.json", "niteroi-osm");
    const code = compileDataSpecToAutkDbJs(
        resolveDataSourceUrls({ data: sources }, SANDBOX_BACKEND_URL_TOKEN).data,
    );

    it("emits a single top-level autk-db import for the sandbox to rewrite", () => {
        // execute_js_code turns exactly this one import into `await import()`.
        const imports = code.match(/^import /gm) ?? [];
        expect(imports).toHaveLength(1);
        expect(code.startsWith("import * as __autkDbMod from '@urban-toolkit/autk-db';")).toBe(true);
    });

    it("inlines the spec and the expected table list", () => {
        expect(code).toContain(`const __expectedTables = ${JSON.stringify(requestedLayerTables(sources))};`);
        expect(code).toContain(JSON.stringify(sources[0].outputTableName));
    });

    it("carries the sandbox URL token rather than a resolved host", () => {
        expect(code).toContain(SANDBOX_BACKEND_URL_TOKEN);
        expect(code).not.toContain("localhost:5002");
    });

    it("returns the layer array the sandbox persists", () => {
        expect(code.trimEnd().endsWith("return __out;")).toBe(true);
    });
});
