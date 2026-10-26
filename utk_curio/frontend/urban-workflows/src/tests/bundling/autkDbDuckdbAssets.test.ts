/**
 * autk-db 3 picks DuckDB's worker and wasm from a copy of `import.meta.url`,
 * which webpack turns into the module's file:// path, so the worker was asked
 * to importScripts a file:// URL and every Autark map and plot hung. The loader
 * writes the URLs literally again, so webpack emits and serves the files.
 *
 * Run against the autk-db this checkout installs, so a new autk-db that no
 * longer has the rewritten shape fails here, not in a browser.
 *
 * It also hands every database the page's one download of DuckDB's module:
 * three maps fetching the 36 MB module at once failed two of them on a cache
 * that could not hold it (net::ERR_CACHE_WRITE_FAILURE in a private window).
 */
import * as fs from "fs";
import * as path from "path";

const { rewriteDuckdbAssetUrls, SHARED_MODULE_SOURCE } = require("../../../webpack/autkDbDuckdbAssets.js");

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

    it("hands the worker the backend address the page resolved", () => {
        // The worker starts from a blob that only runs importScripts, so the
        // blob is where the page's address reaches duckdbExtensionMirror.js.
        const template = region.match(/new Blob\(\[(`[^`]*`)\]/)![1];
        const g = globalThis as any;
        g.__curioBackendUrl = "https://curio.example.org/app/api";
        const e = { mainWorker: "https://curio.example.org/app/worker.js" };
        try {
            // eslint-disable-next-line no-new-func
            const blob = new Function("e", `return ${template};`)(e);
            expect(blob).toBe(
                'self.__curioBackendUrl = "https://curio.example.org/app/api";' +
                'importScripts("https://curio.example.org/app/worker.js");',
            );
        } finally {
            delete g.__curioBackendUrl;
        }
    });

    it("hands every database the page's one download of DuckDB's module", () => {
        expect(region).toContain(SHARED_MODULE_SOURCE);
        expect(region).toMatch(/\.instantiate\(await __curioSharedDuckdbModule\(\w+\.mainModule\)\)/);
        expect(region).not.toMatch(/\.instantiate\(\w+\.mainModule\)/);
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
        expect(() => rewriteDuckdbAssetUrls(
            "//#region src/duckdb-browser.ts\nlet e = import.meta.url;\n" +
            'const w = new URL("./duckdb-eh.wasm", e);\n//#endregion\n',
        )).toThrow(/no importScripts blob/);
        expect(() => rewriteDuckdbAssetUrls(
            "//#region src/duckdb-browser.ts\nlet e = import.meta.url;\n" +
            'const w = new URL("./duckdb-eh.wasm", e);\n' +
            "const b = new Blob([`importScripts(${JSON.stringify(t.mainWorker)});`]);\n//#endregion\n",
        )).toThrow(/instantiate/);
    });
});

describe("the page's one download of DuckDB's module", () => {
    /** The helper the region carries, on a fetch, URL and Blob of the test's. */
    function sharedModule(fetchImpl: jest.Mock) {
        const made: string[] = [];
        const url = { createObjectURL: (blob: { type: string }) => { made.push(blob.type); return `blob:module-${made.length}`; } };
        class FakeBlob {
            type: string;
            constructor(_parts: unknown[], options: { type: string }) { this.type = options.type; }
        }
        // eslint-disable-next-line no-new-func
        const shared = new Function("fetch", "URL", "Blob", `${SHARED_MODULE_SOURCE}\nreturn __curioSharedDuckdbModule;`)(
            fetchImpl, url, FakeBlob,
        ) as (url: string) => Promise<string>;
        return { shared, made };
    }

    const MODULE = "https://curio.example.org/duckdb-eh.wasm";

    it("asks the network once, however many databases start at once", async () => {
        const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 200, blob: async () => "bytes" });
        const { shared, made } = sharedModule(fetchMock);

        const urls = await Promise.all([1, 2, 3].map(() => shared(MODULE)));

        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(urls).toEqual(["blob:module-1", "blob:module-1", "blob:module-1"]);
        expect(made).toEqual(["application/wasm"]);
    });

    it("asks again after a download that failed", async () => {
        const fetchMock = jest.fn()
            .mockResolvedValueOnce({ ok: false, status: 502, blob: async () => "" })
            .mockResolvedValueOnce({ ok: true, status: 200, blob: async () => "bytes" });
        const { shared } = sharedModule(fetchMock);

        await expect(shared(MODULE)).rejects.toThrow(/answered 502/);
        await Promise.resolve();

        await expect(shared(MODULE)).resolves.toBe("blob:module-1");
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });
});
