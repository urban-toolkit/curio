/**
 * Serve DuckDB's spatial extension from Curio, not from the internet (#318).
 *
 * autk-db's `init()` runs `INSTALL spatial; LOAD spatial;`, which duckdb-wasm
 * resolves against `https://extensions.duckdb.org/`. Everything else DuckDB
 * needs is already local — autk-db imports `duckdb-eh.wasm` and
 * `duckdb-browser-eh.worker.js` as webpack assets, so they are served from this
 * instance — but the extension is fetched at run time, by a synchronous
 * XMLHttpRequest **inside duckdb's worker**, on every fresh DuckDB. That is one
 * 23 MB download per grammar run, a node that fails when the CDN blinks, and an
 * Autark node that cannot run at all on an air-gapped install.
 *
 * DuckDB has a setting for this (`custom_extension_repository`) and Curio
 * cannot reach it: autk-db installs the extension inside `init()`, before Curio
 * is handed a connection. The page cannot patch the worker either — the worker
 * has its own global scope, and its URL is a hashed webpack asset.
 *
 * So the redirect is injected into the worker itself, at build time, by this
 * loader. The result is plain: duckdb's worker asks this instance for the file
 * and falls back to the CDN if it is not there, so a duckdb-wasm bump past the
 * vendored version degrades to the old behaviour instead of breaking.
 *
 * The Node side needs none of this: duckdb-wasm keeps installed extensions
 * under `~/.duckdb/extensions/`, which the launcher seeds from the same
 * vendored file (`utk_curio/main.py::seed_duckdb_extensions`).
 */

const DUCKDB_EXTENSION_CDN = "https://extensions.duckdb.org/";

/**
 * The redirect, as source to prepend to duckdb's worker.
 *
 * `mirrorBase` is absolute because the worker runs from a blob-ish asset URL
 * and the backend that serves `/file/` is a different origin from the frontend.
 */
function buildPrelude(mirrorBase) {
  return `/* Curio (#318): DuckDB extensions come from this instance, not the internet. */
(function () {
  if (typeof XMLHttpRequest !== "function") return;
  var CDN = ${JSON.stringify(DUCKDB_EXTENSION_CDN)};
  var MIRROR = ${JSON.stringify(mirrorBase)};
  var open = XMLHttpRequest.prototype.open;
  var send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    var rest = Array.prototype.slice.call(arguments, 2);
    if (typeof url === "string" && url.indexOf(CDN) === 0) {
      this.__curioCdnArgs = [method, url].concat(rest);
      url = MIRROR + url.slice(CDN.length);
    } else {
      this.__curioCdnArgs = null;
    }
    return open.apply(this, [method, url].concat(rest));
  };
  XMLHttpRequest.prototype.send = function (body) {
    var cdnArgs = this.__curioCdnArgs;
    send.call(this, body);
    // duckdb loads extensions with a SYNCHRONOUS request, so the outcome is
    // known here: if this instance does not carry the file (a duckdb-wasm
    // version this checkout has not vendored), ask the CDN as before.
    if (cdnArgs && this.readyState === 4 && this.status !== 200) {
      this.__curioCdnArgs = null;
      open.apply(this, cdnArgs);
      send.call(this, body);
    }
  };
})();
`;
}

/**
 * Where this instance serves `vendor/duckdb-extensions/` from.
 *
 * The backend's `/file/<path>` route, the same one the Autark examples fetch
 * their `.osm.pbf` extracts through. `BACKEND_URL` is already baked into the
 * bundle at build time (see `check_install_build`'s stamp), so the worker gets
 * a URL that matches the instance it was built for.
 */
function mirrorBaseFor(backendUrl) {
  const root = String(backendUrl || "").replace(/\/+$/, "");
  return `${root}/file/vendor/duckdb-extensions/`;
}

/** webpack loader: prepend the redirect to duckdb's worker asset. */
function duckdbExtensionMirrorLoader(source) {
  const backendUrl = process.env.BACKEND_URL || "http://localhost:5002";
  return buildPrelude(mirrorBaseFor(backendUrl)) + source;
}

module.exports = duckdbExtensionMirrorLoader;
module.exports.buildPrelude = buildPrelude;
module.exports.mirrorBaseFor = mirrorBaseFor;
module.exports.DUCKDB_EXTENSION_CDN = DUCKDB_EXTENSION_CDN;
module.exports.raw = false;
