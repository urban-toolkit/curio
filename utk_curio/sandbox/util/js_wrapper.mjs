// js_wrapper.mjs — static template for JS Computation node execution.
//
// Python nodes need no template: app/worker.py::execute_code and
// isolation/child.py exec their code directly.
// Python reads this file, substitutes four placeholders, then pipes the
// result to `node --input-type=commonjs` via stdin.  Placeholders (replaced
// by Python before execution, never present in the running script):
//   DYNAMIC_IMPORTS      : user import statements rewritten as await import() calls
//   ARG_JSON             : JSON-serialized input value (embedded as a JS literal)
//   USER_CODE            : user code indented 4 spaces (body of an async function)
//   OVERPASS_USER_AGENT  : node_runtime.OVERPASS_USER_AGENT, as a JS string literal
//
// The result is written as a single stdout line with a unique prefix so Python
// can extract it without a temp file.  All other stdout lines are user output.

if (typeof self === 'undefined') globalThis.self = globalThis;

const __origFetch = globalThis.fetch;
globalThis.fetch = (url, opts = {}) => {
  if (typeof url === 'string' && url.includes('overpass-api.de')) {
    opts = { ...opts, headers: { ...opts.headers, 'User-Agent': __OVERPASS_USER_AGENT__ } };
  }
  return __origFetch(url, opts);
};

const __logs = [];
const __origLog = console.log;
console.log = (...args) => {
  __logs.push(args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' '));
  __origLog(...args);
};

// A layer chip (#662), `[!! input 0:table_osm_roads !!]`, is written as
// `curio_layer(arg, "table_osm_roads", 0)`: the layer of that name among the
// ones the input carries, as a FeatureCollection, found by its name exactly as
// an Autark spec finds it. The input's circle names it when it is missing. The
// Python twin, with what an input may carry, is util/input_layers.py.
const curio_layer = (value, layer, slot = 0) => {
  const items = value && typeof value === 'object' && !Array.isArray(value)
    && value.dataType === 'outputs' && Array.isArray(value.data)
    ? value.data
    : Array.isArray(value) ? value : [value];
  const named = [];
  for (const item of items) {
    if (!item || typeof item !== 'object') continue;
    let name = null;
    let found = null;
    if ('dataType' in item) {
      name = item.layerName;
      found = item.data;
    } else if (item.geojson && typeof item.geojson === 'object') {
      name = item.name;
      found = item.geojson;
    } else if (item.type === 'FeatureCollection') {
      name = item.name;
      found = item;
    }
    if (typeof name === 'string' && name) named.push([name, found]);
  }
  for (const [name, found] of named) {
    if (name === layer) return found;
  }
  const names = named.map(([name]) => name);
  const has = names.length > 0 ? `Its layers are ${names.join(', ')}.` : 'It carries no named layers.';
  throw new Error(`[!! input ${slot}:${layer} !!]: input ${slot} has no layer ${layer}. ${has}`);
};

const arg = __ARG_JSON__;
const __RESULT_PREFIX = '__CURIO_JSON_RESULT__';

(async () => {
__DYNAMIC_IMPORTS__
  try {
    const __result = await (async function(arg) {
__USER_CODE__
    })(arg);
    try {
      process.stdout.write(__RESULT_PREFIX + JSON.stringify({ success: true, value: __result, logs: __logs }) + '\n', () => process.exit(0));
    } catch (serErr) {
      process.stdout.write(__RESULT_PREFIX + JSON.stringify({ success: false, error: 'Result not JSON-serializable: ' + serErr.message, logs: __logs }) + '\n', () => process.exit(0));
    }
  } catch (e) {
    process.stdout.write(__RESULT_PREFIX + JSON.stringify({ success: false, error: e.message + '\n' + (e.stack || ''), logs: __logs }) + '\n', () => process.exit(0));
  }
})();
