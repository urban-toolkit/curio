// js_wrapper.mjs — static template for JS Computation node execution.
//
// Python nodes need no template: app/worker.py::execute_code and
// isolation/child.py exec their code directly.
// Python reads this file, substitutes three placeholders, then pipes the
// result to `node --input-type=commonjs` via stdin.  Placeholders (replaced
// by Python before execution, never present in the running script):
//   DYNAMIC_IMPORTS  — user import statements rewritten as await import() calls
//   ARG_JSON         — JSON-serialized input value (embedded as a JS literal)
//   USER_CODE        — user code indented 4 spaces (body of an async function)
//
// The result is written as a single stdout line with a unique prefix so Python
// can extract it without a temp file.  All other stdout lines are user output.

if (typeof self === 'undefined') globalThis.self = globalThis;

const __origFetch = globalThis.fetch;
globalThis.fetch = (url, opts = {}) => {
  if (typeof url === 'string' && url.includes('overpass-api.de')) {
    opts = { ...opts, headers: { ...opts.headers, 'User-Agent': 'autk-db/1.3.1' } };
  }
  return __origFetch(url, opts);
};

const __logs = [];
const __origLog = console.log;
console.log = (...args) => {
  __logs.push(args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' '));
  __origLog(...args);
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
