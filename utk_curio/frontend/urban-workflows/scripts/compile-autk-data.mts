// Compile the data sections of a dataflow's Autark nodes to autk-db JavaScript,
// outside the browser.
//
// The CI stress harness drives Curio over HTTP with no browser, but an Autark
// node's data load is compiled in the frontend before it is posted to
// /processJavaScriptCode. Rather than restate that compilation in Python (two
// copies to keep in step), this runs the frontend's own module: Node strips the
// type annotations natively, so no build step and no new dependency.
//
//   node scripts/compile-autk-data.mts docs/examples/11-autark-pbf-loading.json
//
// Prints {"<nodeId>": "<autk-db JavaScript>"} for every autk-grammar node whose
// spec has a non-empty data section. Nodes without one render from upstream
// input only and post nothing to the backend, so they are left out.

import { readFileSync } from 'node:fs';
import {
    SANDBOX_BACKEND_URL_TOKEN,
    compileDataSpecToAutkDbJs,
    resolveDataSourceUrls,
} from '../src/adapters/node/autkDataCompile.ts';

const AUTK_GRAMMAR_TYPE = 'curio.builtin/autk-grammar';

function dataSourcesOf(node: any): any[] {
    let spec: any;
    try {
        spec = JSON.parse(node?.content ?? '');
    } catch {
        return [];
    }
    return Array.isArray(spec?.data) ? spec.data : [];
}

function main(): void {
    const path = process.argv[2];
    if (!path) {
        console.error('usage: node scripts/compile-autk-data.mts <dataflow.json>');
        process.exit(2);
    }

    const parsed = JSON.parse(readFileSync(path, 'utf8'));
    const dataflow = parsed?.dataflow ?? parsed;
    const nodes: any[] = Array.isArray(dataflow?.nodes) ? dataflow.nodes : [];

    const out: Record<string, string> = {};
    for (const node of nodes) {
        if (node?.type !== AUTK_GRAMMAR_TYPE) continue;
        const sources = dataSourcesOf(node);
        if (sources.length === 0) continue;
        // Same two steps the node behavior takes before posting: resolve the
        // relative file URLs against the sandbox token, then compile.
        const resolved = resolveDataSourceUrls({ data: sources }, SANDBOX_BACKEND_URL_TOKEN).data;
        out[node.id] = compileDataSpecToAutkDbJs(resolved);
    }

    process.stdout.write(JSON.stringify(out));
}

main();
