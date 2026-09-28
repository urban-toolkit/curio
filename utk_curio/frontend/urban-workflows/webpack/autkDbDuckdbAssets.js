/**
 * Serve autk-db's DuckDB worker and wasm from this build again.
 *
 * autk-db 3 chooses DuckDB's files at run time, from a copy of
 * `import.meta.url` (`let e = import.meta.url; ... new URL("./duckdb-eh.wasm", e)`),
 * so that a Vite app serves them locally and a CDN import falls back to
 * jsDelivr. webpack only emits and rewrites a `new URL("<file>", import.meta.url)`
 * written out literally. Through the copy it emits nothing, and it replaces
 * `import.meta.url` itself with the module's `file://` path at build time, so
 * DuckDB's worker was asked to `importScripts` a `file://` URL the browser
 * refuses, and every Autark map and plot hung.
 *
 * This loader writes those URLs out literally again, which is what autk-db 2
 * did: webpack emits the four files as assets served by this instance, and
 * duckdb's worker still passes through duckdbExtensionMirror.js (#318).
 *
 * It fails the build, rather than a map at run time, when autk-db's code no
 * longer has the shape it rewrites.
 */

const REGION = /\/\/#region src\/duckdb-browser\.ts[\s\S]*?\/\/#endregion/;

function fail(what) {
  throw new Error(
    `autkDbDuckdbAssets: ${what}. autk-db's browser build changed; see webpack/autkDbDuckdbAssets.js`,
  );
}

function rewriteDuckdbAssetUrls(source) {
  const region = source.match(REGION);
  if (!region) fail("no duckdb-browser region");
  const copy = region[0].match(/let (\w+) = import\.meta\.url;/);
  if (!copy) fail("import.meta.url is no longer copied into a variable");
  const asset = new RegExp(
    `new URL\\(\\s*(?:/\\*[^*]*\\*/\\s*)?("\\./duckdb-[\\w.-]+\\.(?:wasm|js)"),\\s*${copy[1]}\\s*\\)`,
    "g",
  );
  const files = new Set();
  const rewritten = region[0].replace(asset, (_, file) => {
    files.add(file);
    return `new URL(${file}, import.meta.url)`;
  });
  if (files.size === 0) fail("no DuckDB asset URL to rewrite");
  return source.replace(region[0], rewritten);
}

module.exports = function autkDbDuckdbAssets(source) {
  return rewriteDuckdbAssetUrls(source);
};
module.exports.rewriteDuckdbAssetUrls = rewriteDuckdbAssetUrls;
