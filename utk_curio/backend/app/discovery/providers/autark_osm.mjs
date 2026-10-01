// OpenStreetMap layers for one Discovery Catalog download, through autk-db.
//
// Run by providers/autark_osm.py as `node autark_osm.mjs`, with one JSON object
// on stdin:
//
//   { autkDbUrl, queryArea, layers, outDir, userAgent, fixtures }
//
// It calls autk-db's own loadOsm, the loader an Autark map node runs, so a
// download and a map get the same features from the same code. Each layer is
// written as autk-db's getLayer returns it, to <outDir>/<layer>.geojson; its
// coordinates are in autk-db's workspace CRS (EPSG:3395), and the Python side
// moves them to WGS84.
//
// stdout carries two kinds of line for Python, and autk-db's own logging:
//
//   __CURIO_OSM_STAGE__ <phase>       autk-db's onProgress phases
//   __CURIO_OSM_RESULT__ <json>       last: {ok, layers: [{layer, file, features}]} or {ok: false, error}
//
// With `fixtures` set (tests only), fetch answers from recorded Overpass
// responses instead of the network, and autk-db's pauses between requests
// are skipped. With `record` set, the network answers and each answer is
// filed under the same key, which is how those fixtures are made.

import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { gunzipSync, gzipSync } from 'node:zlib';

if (typeof self === 'undefined') globalThis.self = globalThis;

const STAGE = '__CURIO_OSM_STAGE__ ';
const RESULT = '__CURIO_OSM_RESULT__ ';

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

function done(result) {
  process.stdout.write(RESULT + JSON.stringify(result) + '\n', () => process.exit(0));
}

/** The key a recorded answer is filed under: method, URL, and a body hash. */
export function fixtureKey(method, url, body) {
  const hash = body ? ' ' + createHash('sha256').update(String(body)).digest('hex').slice(0, 16) : '';
  return `${method.toUpperCase()} ${url}${hash}`;
}

async function fixtureFetch(root) {
  const index = JSON.parse(await readFile(path.join(root, 'index.json'), 'utf8'));
  return async (input, opts = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    const key = fixtureKey(opts.method || 'GET', url, opts.body);
    const entry = index[key];
    if (!entry) {
      throw new Error(`no recorded Overpass answer for ${key}; record it with this script's record mode (ARCHITECTURE.md, Services)`);
    }
    // Filed gzipped: an Overpass answer is JSON and shrinks tenfold.
    const body = gunzipSync(await readFile(path.join(root, entry.file)));
    return new Response(body, { status: entry.status ?? 200, headers: entry.headers ?? {} });
  };
}

/** The network, with each answer also filed for fixtureFetch (recording only). */
async function recordingFetch(root, realFetch) {
  const indexPath = path.join(root, 'index.json');
  let index = {};
  try {
    index = JSON.parse(await readFile(indexPath, 'utf8'));
  } catch {
    index = {};
  }
  return async (input, opts = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    const key = fixtureKey(opts.method || 'GET', url, opts.body);
    const response = await realFetch(input, opts);
    const body = Buffer.from(await response.arrayBuffer());
    const file = createHash('sha256').update(key).digest('hex').slice(0, 16) + '.gz';
    await writeFile(path.join(root, file), gzipSync(body, { level: 9 }));
    index[key] = { file, status: response.status, headers: { 'content-type': response.headers.get('content-type') ?? '' } };
    await writeFile(indexPath, JSON.stringify(index, null, 2) + '\n');
    return new Response(body, { status: response.status, headers: response.headers });
  };
}

async function main() {
  const input = await readStdin();
  const realFetch = globalThis.fetch;
  const send = input.fixtures
    ? await fixtureFetch(input.fixtures)
    : input.record
      ? await recordingFetch(input.record, realFetch)
      : realFetch;
  globalThis.fetch = (url, opts = {}) => {
    const target = typeof url === 'string' ? url : url?.url ?? '';
    if (target.includes('overpass-api.de')) {
      opts = { ...opts, headers: { ...opts.headers, 'User-Agent': input.userAgent } };
    }
    return send(url, opts);
  };
  if (input.fixtures) {
    // Recorded answers arrive at once; autk-db's pauses and retry backoffs
    // would only make a test wait.
    const realSetTimeout = globalThis.setTimeout;
    globalThis.setTimeout = (fn, _ms, ...args) => realSetTimeout(fn, 0, ...args);
  }

  const { AutkDb } = await import(input.autkDbUrl);
  const db = new AutkDb();
  await db.init();
  const timings = await db.loadOsm({
    queryArea: input.queryArea,
    autoLoadLayers: { layers: input.layers },
    onProgress: (phase) => process.stdout.write(STAGE + phase + '\n'),
  });

  const layers = [];
  for (const entry of timings.layers) {
    const collection = await db.getLayer(entry.layerName);
    const file = path.join(input.outDir, `${entry.layerType}.geojson`);
    await writeFile(file, JSON.stringify(collection));
    layers.push({ layer: entry.layerType, file, features: collection.features.length });
  }
  done({ ok: true, layers });
}

main().catch((error) => done({ ok: false, error: String(error?.message ?? error) }));
