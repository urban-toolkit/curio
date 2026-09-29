/**
 * autk-db 3 picks DuckDB's worker and wasm from a copy of `import.meta.url`,
 * which webpack turns into the module's file:// path, so the worker was asked
 * to importScripts a file:// URL and every Autark map and plot hung. The loader
 * writes the URLs literally again, so webpack emits and serves the files.
 *
 * Run against the autk-db this checkout installs, so a new autk-db that no
 * longer has the rewritten shape fails here, not in a browser.
 */
import * as fs from "fs";
import * as path from "path";

const { rewriteDuckdbAssetUrls } = require("../../../webpack/autkDbDuckdbAssets.js");

const BROWSER_BUILD = path.join(
    __dirname, "../../../node_modules/@urban-toolkit/autk-db/dist/browser.js",
);

const FILES = [
    "./duckdb-mvp.wasm",
    "./duckdb-browser-mvp.worker.js",
    "./duckdb-eh.wasm",
    "./duckdb-browser-eh.worker.js",
];

describe("autk-db's DuckDB files, as webpack sees them", () => {
    const source = fs.readFileSync(BROWSER_BUILD, "utf8");
    const out = rewriteDuckdbAssetUrls(source);
    const region = out.match(/\/\/#region src\/duckdb-browser\.ts[\s\S]*?\/\/#endregion/)![0];

    it("names every file with import.meta.url, the form webpack emits as an asset", () => {
        for (const file of FILES) {
            expect(region).toContain(`new URL("${file}", import.meta.url)`);
        }
    });

    it("leaves no URL built from the copied base", () => {
        const copied = source.match(/let (\w+) = import\.meta\.url;/)![1];
        expect(region).not.toMatch(new RegExp(`"\\./duckdb-[\\w.-]+",\\s*${copied}\\s*\\)`));
    });

    it("changes nothing outside DuckDB's file selection", () => {
        const before = source.replace(/\/\/#region src\/duckdb-browser\.ts[\s\S]*?\/\/#endregion/, "");
        const after = out.replace(/\/\/#region src\/duckdb-browser\.ts[\s\S]*?\/\/#endregion/, "");
        expect(after).toBe(before);
    });
});

describe("a build it does not recognise", () => {
    it("fails the build instead of shipping a map that hangs", () => {
        expect(() => rewriteDuckdbAssetUrls("export const x = 1;\n")).toThrow(/autkDbDuckdbAssets/);
        expect(() => rewriteDuckdbAssetUrls(
            "//#region src/duckdb-browser.ts\nfunction S() { return {}; }\n//#endregion\n",
        )).toThrow(/no longer copied/);
    });
});
