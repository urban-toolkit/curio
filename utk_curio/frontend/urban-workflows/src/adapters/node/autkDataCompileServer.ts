// The Autark data compiler a run on the server uses: the browser's own
// (autkDataCompile.ts), bundled by webpack.autk-data.config.js into
// dist/autk-data-compile.cjs, which utk_curio/common/autk_data_compiler.py runs
// in Node.
//
// It reads an Autark document on stdin, its references already resolved, and
// writes the autk-db JavaScript the node's run in the browser posts to the
// sandbox: the data section's relative file URLs resolved against the sandbox
// token, then compiled with the document's `workspaces`, the two steps
// autkGrammarBehavior takes. A document
// that writes a key autk-grammar 5 renamed, or one a node does not run yet, is
// refused as the node refuses it (contracts/autkGrammar): those words are all
// it writes, on stderr, and it exits with 1, so autk_data_compiler.py fails
// the run with them.

import { readFileSync } from 'fs';
import { autkKeyProblem } from '../../contracts/autkGrammar';
import {
    SANDBOX_BACKEND_URL_TOKEN,
    compileDataSpecToAutkDbJs,
    resolveDataSourceUrls,
} from './autkDataCompile';

const spec = JSON.parse(readFileSync(0, 'utf8'));
const keyProblem = autkKeyProblem(spec);
if (keyProblem) {
    process.stderr.write(`${keyProblem}\n`);
    process.exit(1);
}
const sources: any[] = Array.isArray(spec?.data) ? spec.data : [];
const resolved = resolveDataSourceUrls({ data: sources }, SANDBOX_BACKEND_URL_TOKEN).data;
process.stdout.write(compileDataSpecToAutkDbJs(resolved, { workspaces: spec?.workspaces }));
