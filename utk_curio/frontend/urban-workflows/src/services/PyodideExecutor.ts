/**
 * PyodideExecutor — in-browser Python execution for Curio's Pyodide mode.
 *
 * Replaces the backend sandbox (/processPythonCode) so the app runs without any
 * server. The executor is a singleton that:
 *   1. Lazily loads Pyodide from CDN the first time it is needed (~30 MB, cached).
 *   2. Installs pandas and numpy from Pyodide's bundled package index.
 *   3. Exposes a virtual filesystem at /data/ where user-uploaded files live.
 *   4. Runs user code inside a wrapper that normalises inputs and outputs to the
 *      same {dataType, data} envelope that the backend sandbox returns, so the
 *      rest of the app doesn't need to know which execution path was used.
 *   5. Stores results in an in-memory Map keyed by a `pyodide://` URI.
 *      Downstream nodes resolve these URIs through api.ts#fetchData, which
 *      intercepts the prefix and serves the object directly from the Map.
 */
export const PYODIDE_PREFIX = 'pyodide://';
import { getAllFiles, clearAllFiles } from './IndexedDBFiles';

export interface PyodideResult {
    stdout: string[];
    stderr: string;
    output: { path: string; dataType: string } | Record<string, never>;
}

class PyodideExecutor {
    private static instance: PyodideExecutor;
    private pyodide: any = null;
    private loadPromise: Promise<void> | null = null;
    /** In-memory store: uuid → deserialized data object */
    private dataStore: Map<string, any> = new Map();

    static getInstance(): PyodideExecutor {
        if (!PyodideExecutor.instance) {
            PyodideExecutor.instance = new PyodideExecutor();
        }
        return PyodideExecutor.instance;
    }

    isLoaded(): boolean {
        return this.pyodide !== null;
    }

    /**
     * Lazily load Pyodide from CDN and install pandas/numpy.
     * Calling multiple times is safe — returns the same promise.
     */
    async load(): Promise<void> {
        if (this.pyodide) return;
        if (this.loadPromise) return this.loadPromise;

        this.loadPromise = (async () => {
            // Inject Pyodide CDN script if not already present
            if (!(window as any).loadPyodide) {
                await new Promise<void>((resolve, reject) => {
                    const script = document.createElement('script');
                    script.src = 'https://cdn.jsdelivr.net/pyodide/v0.27.0/full/pyodide.js';
                    script.onload = () => resolve();
                    script.onerror = () => reject(new Error('Failed to load Pyodide script from CDN'));
                    document.head.appendChild(script);
                });
            }

            console.log('[Curio/Pyodide] Initializing runtime…');
            this.pyodide = await (window as any).loadPyodide({
                indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.27.0/full/',
            });

            // Load bundled packages (no network fetch for these)
            await this.pyodide.loadPackage(['pandas', 'numpy']);

            // Create virtual filesystem directory for user-uploaded files
            try { this.pyodide.FS.mkdir('/data'); } catch (_) { /* already exists */ }

            // Restore previously uploaded files from IndexedDB into the virtual FS
            try {
                const saved = await getAllFiles();
                for (const file of saved) {
                    this.pyodide.FS.writeFile(`/data/${file.name}`, file.data);
                }
                if (saved.length > 0) {
                    console.log(`[Curio/Pyodide] Restored ${saved.length} file(s) from IndexedDB`);
                }
            } catch (_) {}

            console.log('[Curio/Pyodide] Ready — pandas + numpy loaded');
        })();

        return this.loadPromise;
    }

    // ── DataStore ────────────────────────────────────────────────────────────

    /** Persist a result object and return its pyodide:// reference key. */
    storeData(data: any): string {
        const key = `${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
        this.dataStore.set(key, data);
        return PYODIDE_PREFIX + key;
    }

    /** Retrieve a stored result by its pyodide:// path. */
    getData(path: string): any {
        const key = path.replace(PYODIDE_PREFIX, '');
        return this.dataStore.get(key);
    }

    isInMemoryPath(path: string): boolean {
        return typeof path === 'string' && path.startsWith(PYODIDE_PREFIX);
    }

    // Virtual Filesystem

    /** Write a file into Pyodide's /data/ directory so user code can read it by path. */
    writeFile(name: string, content: Uint8Array): void {
        if (!this.pyodide) throw new Error('[Curio/Pyodide] Not loaded yet');
        this.pyodide.FS.writeFile(`/data/${name}`, content);
    }

    /** Remove all uploaded files from the virtual FS and IndexedDB. */
    async clearFiles(): Promise<void> {
        if (this.pyodide) {
            try {
                const files = (this.pyodide.FS.readdir('/data') as string[]).filter(f => f !== '.' && f !== '..');
                for (const f of files) this.pyodide.FS.unlink(`/data/${f}`);
            } catch (_) {}
        }
        await clearAllFiles();
    }

    // List files currently available in /data/.
    listFiles(): string[] {
        if (!this.pyodide) return [];
        try {
            return (this.pyodide.FS.readdir('/data') as string[]).filter(f => f !== '.' && f !== '..');
        } catch {
            return [];
        }
    }

    // Execution

    /**
     * Execute user Python code in Pyodide.
     *
     * @param code     Raw user code (un-indented, using `return` to emit output)
     * @param inputRef The upstream node's output ref: {path, dataType} or ""
     * @param boxType  e.g. "DATA_LOADING", "DATA_TRANSFORMATION"
     */
    async execute(code: string, inputRef: any, boxType: string): Promise<PyodideResult> {
        if (!this.pyodide) throw new Error('[Curio/Pyodide] Not loaded yet');

        const stdoutLines: string[] = [];
        let stderrText = '';
        this.pyodide.setStdout({ batched: (s: string) => stdoutLines.push(s) });
        this.pyodide.setStderr({ batched: (s: string) => { stderrText += s + '\n'; } });

        let inputData: any = null;
        if (inputRef && inputRef !== '') {
            if (this.isInMemoryPath(inputRef.path)) {
                inputData = this.getData(inputRef.path);
            } else if (inputRef.data !== undefined) {
                inputData = inputRef;
            }
        }

        // Pass input to Python globals
        this.pyodide.globals.set('_curio_input_raw', inputData ? this.pyodide.toPy(inputData) : null);

        const indented = code.split('\n').map(l => '    ' + l).join('\n');

        const wrapper = `
import sys, traceback, json
import pandas as pd
import numpy as np

def _parse_input(d):
    if d is None:
        return ''
    dataType = d.get('dataType', '')
    if dataType == 'dataframe':
        return pd.DataFrame.from_dict(d['data'])
    elif dataType == 'list':
        return d.get('data', [])
    elif dataType == 'json':
        return d.get('data', {})
    else:
        return d.get('data', '')

def _parse_output(out):
    if isinstance(out, pd.DataFrame):
        # Use orient='list' to match sandbox format: {col: [val1, val2, ...]}
        clean = out.astype(object).where(pd.notnull(out), None)
        return {'dataType': 'dataframe', 'data': clean.to_dict(orient='list')}
    elif isinstance(out, dict):
        return {'dataType': 'json', 'data': out}
    elif isinstance(out, list):
        return {'dataType': 'list', 'data': out}
    elif out is None:
        return {'dataType': 'str', 'data': ''}
    else:
        return {'dataType': 'str', 'data': str(out)}

def userCode(arg):
${indented}

_curio_error = None
_curio_result = None
try:
    _input_py = _curio_input_raw.to_py() if hasattr(_curio_input_raw, 'to_py') else _curio_input_raw
    _arg = _parse_input(_input_py)
    _raw = userCode(_arg)
    _curio_result = _parse_output(_raw)
except Exception:
    _curio_error = traceback.format_exc()
`;

        try {
            await this.pyodide.runPythonAsync(wrapper);
        } catch (jsError: any) {
            return { stdout: stdoutLines, stderr: String(jsError), output: {} };
        }

        const error = this.pyodide.globals.get('_curio_error');
        if (error) {
            return { stdout: stdoutLines, stderr: String(error), output: {} };
        }

        const rawResult = this.pyodide.globals.get('_curio_result');
        if (!rawResult) {
            return { stdout: stdoutLines, stderr: 'No output returned (did you forget `return`?)', output: {} };
        }

        // Convert PyProxy → plain JS object
        const result: any = rawResult.toJs
            ? rawResult.toJs({ dict_converter: Object.fromEntries })
            : rawResult;

        const path = this.storeData(result);

        return {
            stdout: stdoutLines,
            stderr: stderrText,
            output: { path, dataType: result.dataType },
        };
    }
}

export const pyodideExecutor = PyodideExecutor.getInstance();
