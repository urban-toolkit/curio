/**
 * End an autk-db database: the worker DuckDB-Wasm runs it in, and with it the
 * WebAssembly that worker compiled.
 *
 * autk-db has no close of its own, and autk-grammar makes a database for every
 * run, so each draw of an Autark map started a worker that nothing ended. The
 * Crown Heights dashboard draws three maps a day: in Firefox, which caps the
 * WebAssembly code a page may compile, the second day picked ran out of it
 * ("failed to allocate executable memory for module", then "out of memory")
 * and its maps never drew. Other browsers only kept growing.
 *
 * It reaches autk-db's private `db` (DuckDB-Wasm's AsyncDuckDB); a database
 * without one, from another autk-db, is left as it is. Never throws.
 */
export function closeAutkDb(autkDb: unknown): void {
    const duckdb = (autkDb as { db?: { terminate?: () => unknown } } | null | undefined)?.db;
    if (typeof duckdb?.terminate !== 'function') return;
    try {
        void Promise.resolve(duckdb.terminate()).catch(() => undefined);
    } catch {
        // A worker that cannot be ended must not fail the run that drops it.
    }
}

/**
 * End the database autk-grammar made for *grammar*'s run: its engine's
 * context, where a raster source's database lands too (autkRasters).
 */
export function closeGrammarDb(grammar: unknown): void {
    closeAutkDb((grammar as { grammarEngine?: { context?: unknown } } | null | undefined)?.grammarEngine?.context);
}
