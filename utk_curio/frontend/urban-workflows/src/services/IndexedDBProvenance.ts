/**
 * IndexedDB persistence layer for provenance records in Pyodide mode.
 *
 * In the original client-server setup, provenance (execution history) is stored
 * in a backend database. Pyodide mode has no backend, so each box execution is
 * appended here instead. Records survive page refresh and are reloaded by
 * ProvenanceProvider on mount so the provenance graph remains intact.
 *
 * Key format: "<workflow_name>__<activity_name>" (double-underscore separator).
 */
const DB_NAME = 'curio_provenance';
const DB_VERSION = 1;
const STORE_NAME = 'box_executions';

export interface ExecRecord {
    inputs: string[];
    outputs: string[];
    code: string;
}

function openDB(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(DB_NAME, DB_VERSION);
        req.onupgradeneeded = () => {
            req.result.createObjectStore(STORE_NAME, { keyPath: 'key' });
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

export async function appendExecRecord(
    workflow: string,
    activity: string,
    record: ExecRecord
): Promise<ExecRecord[]> {
    const db = await openDB();
    const key = `${workflow}__${activity}`;
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        const store = tx.objectStore(STORE_NAME);
        const getReq = store.get(key);
        getReq.onsuccess = () => {
            const existing: ExecRecord[] = getReq.result?.records ?? [];
            const updated = [...existing, record];
            store.put({ key, records: updated });
            resolve(updated);
        };
        getReq.onerror = () => reject(getReq.error);
    });
}

export async function getAllExecRecords(): Promise<Record<string, ExecRecord[]>> {
    const db = await openDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readonly');
        const req = tx.objectStore(STORE_NAME).getAll();
        req.onsuccess = () => {
            const result: Record<string, ExecRecord[]> = {};
            for (const item of req.result) {
                result[item.key] = item.records;
            }
            resolve(result);
        };
        req.onerror = () => reject(req.error);
    });
}

export async function clearExecRecords(): Promise<void> {
    const db = await openDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        const req = tx.objectStore(STORE_NAME).clear();
        req.onsuccess = () => resolve();
        req.onerror = () => reject(req.error);
    });
}
