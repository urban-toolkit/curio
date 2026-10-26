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
 * The worker starts from a blob that only runs `importScripts`, so it cannot
 * see the page. The loader also puts the backend address the page resolved
 * (`globalThis.__curioBackendUrl`, set by index.tsx) into that blob, which is
 * where duckdbExtensionMirror.js reads it.
 *
 * Every Autark map and plot builds its own DuckDB, and each one's worker
 * fetched DuckDB's 36 MB module itself. Three maps on a dashboard asked for it
 * at once; behind a proxy that compresses it on the fly, so with no length,
 * Chromium hands the three to one cache write, and a cache that cannot hold the
 * module (a private window's, in memory) fails the other two
 * (net::ERR_CACHE_WRITE_FAILURE): two maps never drew. The page now downloads
 * the module once and hands every database the same copy, as a blob URL
 * (SHARED_MODULE_SOURCE); a download that fails is asked again by the next.
 *
 * It fails the build, rather than a map at run time, when autk-db's code no
 * longer has the shape it rewrites.
 */

const REGION = /\/\/#region src\/duckdb-browser\.ts[\s\S]*?\/\/#endregion/;

/** One download of each DuckDB module the page's databases instantiate. */
const SHARED_MODULE_SOURCE = `const __curioDuckdbModules = new Map();
function __curioSharedDuckdbModule(url) {
\tlet shared = __curioDuckdbModules.get(url);
\tif (!shared) {
\t\tshared = fetch(url).then((response) => {
\t\t\tif (!response.ok) throw new Error(\`DuckDB's module \${url} answered \${response.status}\`);
\t\t\treturn response.blob();
\t\t}).then((blob) => URL.createObjectURL(new Blob([blob], { type: "application/wasm" })));
\t\t__curioDuckdbModules.set(url, shared);
\t\tshared.catch(() => __curioDuckdbModules.delete(url));
\t}
\treturn shared;
}
`;

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
  let rewritten = region[0].replace(asset, (_, file) => {
    files.add(file);
    return `new URL(${file}, import.meta.url)`;
  });
  if (files.size === 0) fail("no DuckDB asset URL to rewrite");
  const blob = /`importScripts\(\$\{JSON\.stringify\((\w+)\.mainWorker\)\}\);`/;
  if (!blob.test(rewritten)) fail("no importScripts blob for DuckDB's worker");
  rewritten = rewritten.replace(
    blob,
    (_, bundle) =>
      "`self.__curioBackendUrl = ${JSON.stringify(String(globalThis.__curioBackendUrl || \"\"))};" +
      `importScripts(\${JSON.stringify(${bundle}.mainWorker)});\``,
  );
  const instantiate = /\.instantiate\((\w+)\.mainModule\)/;
  if (!instantiate.test(rewritten)) fail("no instantiate(bundle.mainModule) to hand the shared module");
  rewritten = rewritten.replace(
    instantiate,
    (_, bundle) => `.instantiate(await __curioSharedDuckdbModule(${bundle}.mainModule))`,
  );
  // After the region's own opening line, so the region still starts as it did.
  rewritten = rewritten.replace(/^(.*\n)/, (line) => line + SHARED_MODULE_SOURCE);
  return source.replace(region[0], rewritten);
}

module.exports = function autkDbDuckdbAssets(source) {
  return rewriteDuckdbAssetUrls(source);
};
module.exports.rewriteDuckdbAssetUrls = rewriteDuckdbAssetUrls;
module.exports.SHARED_MODULE_SOURCE = SHARED_MODULE_SOURCE;
