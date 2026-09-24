/**
 * Rebuild the `/get` JSON envelope from an Arrow IPC response.
 *
 * The sandbox has served Arrow on an `Accept` header since May; nothing asked
 * for it. On the 100-user stress tier the Arrow path finished in 100.9s
 * against 467.7s for JSON, because it skips the pandas materialisation and the
 * JSON encode that make an artifact fetch expensive.
 *
 * This rebuilds the exact envelope the JSON path returns, so none of the nine
 * `fetchData` consumers change and the JSON path stays reachable as a
 * fallback. That costs the client-side win -- materialising columns into JS
 * arrays is most of the work, and `tableFromIPC` itself is 0.3ms against 91ms
 * for `JSON.parse` on a 200k-row frame -- and getting that back means teaching
 * consumers to read the table directly, which is a separate change.
 */
import type { Table, Vector } from "apache-arrow";

export type ArrowHeaders = Record<string, string | null | undefined>;

export type ArtifactEnvelope = {
    data: any;
    dataType?: string;
    schema?: Record<string, string>;
    filename?: string;
    preview?: boolean;
    previewRows?: number;
    totalRows?: number;
};

function header(headers: ArrowHeaders, name: string): string | undefined {
    const value = headers[name] ?? headers[name.toLowerCase()];
    return value == null || value === "" ? undefined : value;
}

function parseJsonHeader(headers: ArrowHeaders, name: string): any {
    const raw = header(headers, name);
    if (raw === undefined) return undefined;
    try {
        return JSON.parse(raw);
    } catch {
        return undefined;
    }
}

function cell(value: unknown): unknown {
    if (typeof value === "bigint") {
        // Arrow keeps int64 as BigInt. The JSON path sends a plain number, and
        // consumers do arithmetic and `JSON.stringify` on these -- the latter
        // THROWS on a BigInt, which would break the data export node on
        // contact. Same 2^53 ceiling the JSON path already had, since
        // `JSON.parse` would have produced a double anyway.
        return Number(value);
    }
    if (typeof value === "number" && !Number.isFinite(value)) {
        // `normalize_dataframe_for_json` scrubs NaN and infinities to null on
        // the JSON path; Arrow carries them natively. Without this every chart
        // gains a NaN where it used to have a gap.
        return null;
    }
    return value;
}

function columnToArray(vector: Vector | null): unknown[] {
    if (!vector) return [];
    const out = new Array(vector.length);
    for (let i = 0; i < vector.length; i++) out[i] = cell(vector.get(i));
    return out;
}

/** Turn one Arrow IPC response into the envelope the canvas already reads. */
export function tableToEnvelope(table: Table, headers: ArrowHeaders): ArtifactEnvelope {
    const kind = header(headers, "X-Curio-Kind");
    const encoded = (header(headers, "X-Curio-Encoded-Object-Columns") || "")
        .split(",")
        .filter(Boolean);

    const columns: Record<string, unknown[]> = {};
    for (const name of table.schema.names) {
        columns[String(name)] = columnToArray(table.getChild(String(name)));
    }
    for (const name of encoded) {
        // Object columns ride as JSON strings here; the JSON path sends them
        // already parsed (`_restore_frame_from_parquet`).
        const column = columns[name];
        if (!column) continue;
        columns[name] = column.map((value) =>
            typeof value === "string" ? safeParse(value) : value,
        );
    }

    const envelope: ArtifactEnvelope = { data: columns };
    if (kind) envelope.dataType = kind;
    const filename = header(headers, "X-Curio-Filename");
    if (filename) envelope.filename = filename;
    const schema = parseJsonHeader(headers, "X-Curio-Schema");
    if (schema) envelope.schema = schema;

    if (header(headers, "X-Curio-Preview") === "true") {
        envelope.preview = true;
        const previewRows = Number(header(headers, "X-Curio-Preview-Rows"));
        const totalRows = Number(header(headers, "X-Curio-Total-Rows"));
        if (Number.isFinite(previewRows)) envelope.previewRows = previewRows;
        if (Number.isFinite(totalRows)) envelope.totalRows = totalRows;
    }
    return envelope;
}

function safeParse(value: string): unknown {
    try {
        return JSON.parse(value);
    } catch {
        return value;
    }
}
