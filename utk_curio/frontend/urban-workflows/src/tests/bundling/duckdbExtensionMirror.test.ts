/**
 * The build-time redirect that keeps DuckDB's spatial extension local (#318).
 *
 * duckdb's worker downloads the extension from extensions.duckdb.org on every
 * fresh database — 23 MB per grammar run, a node that fails when the CDN
 * blinks, and no Autark node at all on an air-gapped install. Curio ships the
 * extension and teaches the worker to ask this instance for it.
 *
 * This is a build artifact, so what can be tested here is the transform: that
 * the emitted worker really carries the redirect, that the redirect rewrites
 * the URLs it should and no others, and that a file this instance does not
 * carry still reaches the CDN. The end-to-end claim (a map node runs with
 * extensions.duckdb.org unreachable) is an e2e run, not a unit test.
 */
const mirror = require("../../../webpack/duckdbExtensionMirror.js");

const { DUCKDB_EXTENSION_CDN, buildPrelude, mirrorBaseFor } = mirror;
const BASE = "http://localhost:5002/file/vendor/duckdb-extensions/";

describe("where the mirror lives", () => {
  it("is the backend's own /file/ route", () => {
    expect(mirrorBaseFor("http://localhost:5002")).toBe(BASE);
  });

  it("does not double the slash", () => {
    expect(mirrorBaseFor("http://localhost:5002/")).toBe(BASE);
  });
});

describe("the emitted worker", () => {
  const worker = mirror("self.onmessage = function () {};\n");

  it("keeps duckdb's own source", () => {
    expect(worker).toContain("self.onmessage = function () {};");
  });

  it("carries the redirect ahead of it", () => {
    expect(worker.indexOf("XMLHttpRequest.prototype.open")).toBeLessThan(
      worker.indexOf("self.onmessage"),
    );
  });
});

/** Run the prelude against a fake XHR and report where each request went. */
function runPrelude(responses: Record<string, number>) {
  const attempts: string[] = [];
  class FakeXHR {
    readyState = 0;
    status = 0;
    private url = "";
    open(_method: string, url: string) {
      this.url = url;
    }
    send() {
      attempts.push(this.url);
      this.readyState = 4;
      this.status = responses[this.url] ?? 404;
    }
  }
  const scope: any = { XMLHttpRequest: FakeXHR };
  // eslint-disable-next-line no-new-func
  new Function("XMLHttpRequest", `${buildPrelude(BASE)}`).call(scope, FakeXHR);
  return { FakeXHR, attempts };
}

describe("the redirect itself", () => {
  const CDN_URL = `${DUCKDB_EXTENSION_CDN}v1.5.1/wasm_eh/spatial.duckdb_extension.wasm`;
  const MIRROR_URL = `${BASE}v1.5.1/wasm_eh/spatial.duckdb_extension.wasm`;

  it("sends the extension request to this instance", () => {
    const { FakeXHR, attempts } = runPrelude({ [MIRROR_URL]: 200 });
    const xhr = new FakeXHR();
    xhr.open("GET", CDN_URL);
    xhr.send();

    expect(attempts).toEqual([MIRROR_URL]);
  });

  it("falls back to the CDN when this instance has no such file", () => {
    // A duckdb-wasm bump asking for a version nobody vendored: the old
    // behaviour, not a broken node.
    const { FakeXHR, attempts } = runPrelude({ [CDN_URL]: 200 });
    const xhr = new FakeXHR();
    xhr.open("GET", CDN_URL);
    xhr.send();

    expect(attempts).toEqual([MIRROR_URL, CDN_URL]);
  });

  it("leaves every other request untouched", () => {
    const other = "http://localhost:5002/file/docs/examples/data/niteroi.osm.pbf";
    const { FakeXHR, attempts } = runPrelude({ [other]: 200 });
    const xhr = new FakeXHR();
    xhr.open("GET", other);
    xhr.send();

    expect(attempts).toEqual([other]);
  });

  it("does not retry a request that succeeded", () => {
    const { FakeXHR, attempts } = runPrelude({ [MIRROR_URL]: 200 });
    const xhr = new FakeXHR();
    xhr.open("GET", CDN_URL);
    xhr.send();
    xhr.send();

    expect(attempts).toEqual([MIRROR_URL, MIRROR_URL]);
  });
});
