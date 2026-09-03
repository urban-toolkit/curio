/**
 * `process.env.BACKEND_URL` may be read in exactly one place.
 *
 * dotenv-webpack inlines it at build time, so every direct read bakes one
 * backend address into the bundle and silently breaks any stack on another
 * port. Read it through utils/backendUrl.ts, which resolves at runtime. This
 * test exists because the direct reads had regrown to nineteen sites.
 */
import * as fs from 'fs';
import * as path from 'path';

const SRC = path.resolve(__dirname, '..');

// The helper itself, and tests that legitimately SET the variable.
const ALLOWED = new Set([
    'utils/backendUrl.ts',
    'tests/backendUrl.test.ts',
    'tests/backendUrlSingleSource.test.ts',
    'tests/PythonInterpreter.test.ts',
    'tests/JavaScriptInterpreter.test.ts',
]);

function walk(dir: string, out: string[] = []): string[] {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(full, out);
        else if (/\.(ts|tsx|js|jsx)$/.test(entry.name)) out.push(full);
    }
    return out;
}

test('process.env.BACKEND_URL is read only in utils/backendUrl.ts', () => {
    const offenders: string[] = [];
    for (const file of walk(SRC)) {
        const rel = path.relative(SRC, file).split(path.sep).join('/');
        if (ALLOWED.has(rel)) continue;
        const lines = fs.readFileSync(file, 'utf8').split('\n');
        lines.forEach((line, i) => {
            if (line.includes('process.env.BACKEND_URL')) offenders.push(rel + ':' + (i + 1) + ': ' + line.trim());
        });
    }
    expect(offenders).toEqual([]);
});
