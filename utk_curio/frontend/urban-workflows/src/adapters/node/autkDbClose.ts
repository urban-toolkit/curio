/**
 * End an autk-db database: the worker DuckDB-Wasm runs it in, and with it the
 * WebAssembly that worker compiled.
 *
 * autk-db has no close of its own, and every run of an Autark map goes on a
 * database of its own, so each draw of an Autark map started a worker that
 * nothing ended. The Crown Heights dashboard draws three maps a day: in
 * Firefox, which caps the WebAssembly code a page may compile, the second day
 * picked ran out of it ("failed to allocate executable memory for module",
 * then "out of memory") and its maps never drew. Other browsers only kept
 * growing.
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
 * A fresh autk-db database, as autk-grammar's data adapter makes its own. One
 * whose `init()` fails, as when its worker cannot fetch the spatial
 * extension, is ended before the failure is passed on.
 */
export async function newAutkDb(): Promise<any> {
    const { AutkDb } = await import('@urban-toolkit/autk-db');
    const db: any = new AutkDb();
    try {
        await db.init();
    } catch (err) {
        closeAutkDb(db);
        throw err;
    }
    return db;
}

/**
 * A data adapter of autk-grammar's: it sets up a document's workspaces and
 * loads each of its sources on the database it is handed, and returns the
 * database the run goes on with.
 */
type DataAdapter = {
    resolveSource(context: unknown, source: any): Promise<unknown>;
    resolveWorkspaces?(context: unknown, workspaces: any[]): Promise<unknown>;
};

/**
 * The database one run of a map node goes on: the node's own, which the node
 * ends whether the run ends or fails (`closeAutkDb`). autk-grammar keeps the
 * database of a run only once the run ends, so the database a failed run had
 * made was out of the node's reach, and its DuckDB worker stayed.
 */
export type RunDatabase = {
    /**
     * *adapter*, the grammar's data adapter, handed this database wherever
     * the run gives it none: the document's workspaces and its first source.
     * The node hands it to the grammar through autk-grammar's
     * `wrapDataAdapter` (5.6.0).
     */
    handedTo<A extends DataAdapter>(adapter: A): A;
    /** The database, made by the first call that needed one; undefined before. */
    readonly db: any;
    /** End the database, if a call made one. */
    close(): void;
};

/**
 * A run's database (`RunDatabase`), made by *make* when the run's workspaces
 * or its first source first need one, as the grammar's data adapter makes its
 * own: a run with no source makes none.
 */
export function runDatabase(make: () => Promise<any> = newAutkDb): RunDatabase {
    let db: any;
    let making: Promise<any> | null = null;
    const made = (): Promise<any> => {
        making ??= make().then((database) => (db = database));
        return making;
    };
    return {
        handedTo<A extends DataAdapter>(adapter: A): A {
            const resolveWorkspaces = adapter.resolveWorkspaces;
            return {
                ...adapter,
                resolveSource: async (context: unknown, source: any) => adapter.resolveSource(context ?? await made(), source),
                ...(typeof resolveWorkspaces === 'function'
                    ? {
                        resolveWorkspaces: async (context: unknown, workspaces: any[]) =>
                            resolveWorkspaces.call(adapter, context ?? await made(), workspaces),
                    }
                    : {}),
            };
        },
        get db() {
            return db;
        },
        close() {
            closeAutkDb(db);
        },
    };
}
