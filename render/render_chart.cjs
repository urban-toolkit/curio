// Renders the Open files card's chart from the branch's own code, on sample
// rows, as SVG inside an HTML page shaped like the monitor's card.
//
//   node render_chart.cjs <worktree> <out dir>
//
// The chart's lines come from openFilesSeries.ts and its spec from
// MonitorCharts.tsx's linesOverTimeSpec, transpiled as they are; Vega draws the
// SVG, in a card 900 px wide.
"use strict";

const fs = require("fs");
const path = require("path");
const Module = require("module");

const [worktree, outDir] = process.argv.slice(2);
const frontend = path.join(worktree, "utk_curio/frontend/urban-workflows");
const nodeModules = path.join(frontend, "node_modules");
const src = path.join(frontend, "src");
const built = path.join(outDir, "built");

// Modules resolve from the frontend's node_modules. Vega's module build has a
// top-level await, which require() refuses, so both libraries load as their
// single-file builds, as the Jest suites load Vega.
process.env.NODE_PATH = nodeModules;
Module._initPaths();
// Copied as .cjs: in a package of "type": "module" the builds would load as
// ES modules, which leave their exports on globalThis.
const vendor = path.join(outDir, "vendor");
fs.mkdirSync(vendor, { recursive: true });
const BUILDS = {
  vega: path.join(vendor, "vega.cjs"),
  "vega-lite": path.join(vendor, "vega-lite.cjs"),
};
fs.copyFileSync(path.join(nodeModules, "vega/build/vega.js"), BUILDS.vega);
fs.copyFileSync(path.join(nodeModules, "vega-lite/build/vega-lite.min.js"), BUILDS["vega-lite"]);
const resolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
  return BUILDS[request] ?? resolve.call(this, request, ...rest);
};

const ts = require(path.join(nodeModules, "typescript"));

const FILES = [
  "pages/monitor/MonitorCharts.tsx",
  "pages/monitor/chartColors.ts",
  "pages/monitor/openFilesSeries.ts",
  "utils/diagnosticsBundle.ts",
  "components/tooltip/vegaTooltip.ts",
];
for (const file of FILES) {
  const source = fs.readFileSync(path.join(src, file), "utf8");
  const out = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true,
    },
    fileName: file,
  });
  const target = path.join(built, file.replace(/\.tsx?$/, ".js"));
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, out.outputText);
}

const { linesOverTimeSpec } = require(path.join(built, "pages/monitor/MonitorCharts.js"));
const { openFilesLines, SERVERS } = require(path.join(built, "pages/monitor/openFilesSeries.js"));
const { formatOpenFiles } = require(path.join(built, "utils/diagnosticsBundle.js"));
const vega = require("vega");
const lite = require("vega-lite");

const HOUR = 3600000;
const stamp = (ms) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");

/** A day-shaped wobble, so the lines look like a server's. */
function wobble(hour, size) {
  return Math.round(size * Math.sin((hour / 24) * 2 * Math.PI) + size * 0.4 * Math.sin(hour * 1.7));
}

function payload(samples, computedAt) {
  return {
    computedAt: stamp(computedAt),
    startedAt: samples[0].at,
    maxDays: 90,
    intervalSeconds: 3600,
    warnAbovePercent: 80,
    clearBelowPercent: 70,
    samples,
  };
}

// A healthy instance: a day and a half since its start, the launcher's limit.
function healthy() {
  const start = Date.parse("2026-11-05T09:12:04Z");
  const samples = [];
  for (let hour = 0; hour < 36; hour += 1) {
    samples.push({
      at: stamp(start + hour * HOUR),
      backend: { open: 190 + wobble(hour, 22) + Math.round(hour * 0.6), limit: 65536 },
      sandbox: { open: 88 + Math.abs(wobble(hour + 5, 9)), limit: 65536 },
    });
  }
  return payload(samples, start + 35 * HOUR + 20 * 60000);
}

// A leak: the backend's count climbs over five days toward Docker's default
// limit of 1,024, as stable's did. Sampled hourly; it passes 80% (819) on day 4.
function leak() {
  const start = Date.parse("2026-11-01T06:40:11Z");
  const samples = [];
  for (let hour = 0; hour < 120; hour += 1) {
    const climb = Math.round(140 + (hour / 119) * 860);
    samples.push({
      at: stamp(start + hour * HOUR),
      backend: { open: Math.min(1024, climb + wobble(hour, 12)), limit: 1024 },
      sandbox: { open: 92 + Math.abs(wobble(hour + 3, 8)), limit: 1024 },
    });
  }
  return payload(samples, start + 119 * HOUR + 25 * 60000);
}

// The first hour after a start (a deploy): one sample.
function firstHour() {
  const start = Date.parse("2026-11-06T21:04:31Z");
  return payload([{
    at: stamp(start),
    backend: { open: 187, limit: 65536 },
    sandbox: { open: 91, limit: 65536 },
  }], start + 25 * 60000);
}

/** What OpenFilesSection hands LinesOverTime, and what VegaChart compiles. */
function chartSvg(data, width) {
  const lines = openFilesLines(data);
  const first = Date.parse(data.samples[0].at);
  const end = Math.max(Date.parse(data.computedAt), first + data.intervalSeconds * 1000);
  const spec = linesOverTimeSpec({
    rows: lines.points,
    timeField: "t",
    valueField: "files",
    seriesField: "line",
    valueTitle: "files",
    seriesTitle: "line",
    timeDomain: [first, end],
    colors: lines.colors,
    logY: true,
    dashed: lines.dashed,
    points: data.samples.length === 1,
  });
  const compiled = lite.compile({ ...spec, width, height: 160, autosize: { type: "fit-x", contains: "padding" } }).spec;
  const view = new vega.View(vega.parse(compiled), { renderer: "none" });
  return view.toSVG();
}

function card(data, svg) {
  const last = data.samples[data.samples.length - 1];
  const when = new Date(last.at).toLocaleString("en-US", { timeZone: "UTC" });
  const counts = SERVERS.map((server) => formatOpenFiles(server, last[server])).join(" · ");
  const font = path.join(src, "assets/fonts/rubik-latin.woff2");
  return `<!doctype html><html><head><meta charset="utf-8"><style>
@font-face { font-family: Rubik; src: url("file://${font}") format("woff2"); font-weight: 300 900; }
body { margin: 0; padding: 16px 20px; background: #f0f0f0; font-family: Rubik, -apple-system, Helvetica, Arial, sans-serif; color: #1E1F23; }
.heading { margin: 0 0 10px; font-size: 13px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: #6B6B76; }
.card { background: #fff; border: 1px solid #E5E5E7; border-radius: 8px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); padding: 14px 16px; width: 900px; box-sizing: border-box; }
.sub { margin: 0 0 8px; font-size: 12px; font-weight: 600; color: #6B6B76; }
.caption { margin: 8px 0 0; font-size: 12px; color: #6B6B76; }
</style></head><body><div id="shot"><h2 class="heading">Hardware</h2><div class="card">
<h3 class="sub">Open files</h3>
${svg}
<p class="caption">Last sample, ${when}: ${counts}.</p>
<p class="caption">A sample every hour since the backend started, at most the last ${data.maxDays} days. A server above ${data.warnAbovePercent}% of its limit adds an entry to Recent errors.</p>
</div></div></body></html>`;
}

fs.mkdirSync(outDir, { recursive: true });
for (const [name, data] of [["healthy", healthy()], ["leak", leak()], ["first-hour", firstHour()]]) {
  chartSvg(data, 866).then((svg) => {
    fs.writeFileSync(path.join(outDir, `${name}.html`), card(data, svg));
    const last = data.samples[data.samples.length - 1];
    console.log(name, data.samples.length, "samples; last", JSON.stringify(last));
  });
}
