// The Autark data compiler a run on the server uses: the browser's own
// (autkDataCompile.ts), bundled by webpack.autk-data.config.js into
// dist/autk-data-compile.cjs, which utk_curio/common/autk_data_compiler.py runs
// in Node.
//
// It reads an Autark document on stdin, its references already resolved, and
// writes the autk-db JavaScript the node's run in the browser posts to the
// sandbox: the data section's relative file URLs resolved against the sandbox
// token, then compiled, the two steps autkGrammarBehavior takes.

import { readFileSync } from 'fs';
import {
    SANDBOX_BACKEND_URL_TOKEN,
    compileDataSpecToAutkDbJs,
    resolveDataSourceUrls,
} from './autkDataCompile';

const spec = JSON.parse(readFileSync(0, 'utf8'));
const sources: any[] = Array.isArray(spec?.data) ? spec.data : [];
const resolved = resolveDataSourceUrls({ data: sources }, SANDBOX_BACKEND_URL_TOKEN).data;
process.stdout.write(compileDataSpecToAutkDbJs(resolved));
