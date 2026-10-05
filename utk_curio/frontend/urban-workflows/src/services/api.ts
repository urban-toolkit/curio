import { getToken } from "../utils/authApi";
import { backendUrl } from "../utils/backendUrl";
import { embeddedArtifact, EmbeddedEnvelope } from "../standalone/dashboardPayload";

export const ARROW_IPC_MIME = "application/vnd.apache.arrow.stream";

/**
 * Fetch an artifact as Arrow, falling back to JSON.
 *
 * The sandbox serves the same artifact either way. Arrow skips the pandas
 * materialisation and the JSON encode, which on the 100-user stress tier was
 * the difference between 467.7s and 100.9s server-side, and it sends roughly
 * half the bytes. It cannot serve every kind -- a dict, a list or a raster
 * comes back 415 -- so JSON stays the path for those and for any response
 * that is not a clean Arrow 200.
 */
async function fetchArtifactAsArrow(url: string, token: string | null | undefined) {
    const response = await fetch(url, {
        headers: {
            Accept: ARROW_IPC_MIME,
            // Geometry arrives as WKB on this path, so the sandbox refuses a
            // geodataframe unless the client says it can decode it (utils/wkb).
            "X-Curio-Accept-Geometry": "wkb",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
    });
    if (!response.ok) {
        // 415 is the sandbox saying "not a tabular kind" (or geometry without
        // the opt-in), which is an ordinary answer, not a failure.
        return null;
    }
    const contentType = response.headers.get("Content-Type") || "";
    if (!contentType.includes(ARROW_IPC_MIME)) {
        return null;
    }
    // Imported here, not at module scope: apache-arrow lives in a lazy chunk
    // (autk-db pulls it the same way), and a static import would put it in the
    // main bundle and slow first paint for everyone, including the people who
    // never open a data pool.
    const [{ tableFromIPC }, { tableToEnvelope }] = await Promise.all([
        import("apache-arrow"),
        import("./arrowEnvelope"),
    ]);
    const buffer = await response.arrayBuffer();
    const headers: Record<string, string> = {};
    response.headers.forEach((value, key) => {
        headers[key] = value;
    });
    const table = tableFromIPC(new Uint8Array(buffer));
    // tableFromIPC does NOT throw on a truncated or corrupt stream: it returns
    // a table with no columns. Without this check a half-delivered response
    // would render as an artifact with no data and no error, which is the
    // worst of the available outcomes. A genuinely empty frame still has its
    // columns, so this only catches the broken case.
    if (table.schema.names.length === 0) {
        throw new Error("Arrow response decoded to an empty table");
    }
    // The sandbox streams the table a batch at a time (#408), so a response
    // cut short part-way decodes to fewer rows, again without an error. It
    // says how many rows it sent; a different count is a broken response,
    // not a smaller artifact.
    const announced = response.headers.get("X-Curio-Rows");
    if (announced !== null && table.numRows !== Number(announced)) {
        throw new Error(`Arrow response ended after ${table.numRows} of ${announced} rows`);
    }
    return tableToEnvelope(table, headers);
}

/** What the preview endpoint sends back for a frame it had to cut down. */
const PREVIEW_ROWS = 100;

/**
 * The first `PREVIEW_ROWS` of an embedded artifact, shaped like the preview
 * endpoint's answer.
 *
 * The sandbox previews by taking `raw.head(max_rows)` and then serialising, so
 * a dataframe comes back as its columns cut to length and a geodataframe as its
 * first features. Anything that is not a frame it sends whole, with no preview
 * keys at all, and so does this.
 */
function previewOfEmbedded(fileName: string, envelope: EmbeddedEnvelope) {
    const body: any = { ...envelope, filename: fileName };
    const data: any = envelope.data;

    if (envelope.dataType === "geodataframe" && data && Array.isArray(data.features)) {
        const total = data.features.length;
        if (total <= PREVIEW_ROWS) return body;
        body.data = { ...data, features: data.features.slice(0, PREVIEW_ROWS) };
        body.preview = true;
        body.previewRows = PREVIEW_ROWS;
        body.totalRows = total;
        return body;
    }

    if (envelope.dataType === "dataframe" && data && typeof data === "object") {
        const columns = Object.keys(data);
        const first = columns.length ? data[columns[0]] : null;
        if (!Array.isArray(first) || first.length <= PREVIEW_ROWS) return body;
        const cut: Record<string, unknown> = {};
        for (const name of columns) {
            const column = data[name];
            cut[name] = Array.isArray(column) ? column.slice(0, PREVIEW_ROWS) : column;
        }
        body.data = cut;
        body.preview = true;
        body.previewRows = PREVIEW_ROWS;
        body.totalRows = first.length;
        return body;
    }

    // A dict, a list, a raster: the endpoint sends these whole.
    return body;
}

export async function fetchData(fileName: string) {
    // A standalone dashboard was served with its rows inside it. Checked before
    // the request rather than after a failure, because the whole point is that
    // the page never reaches the network.
    const embedded = embeddedArtifact(fileName);
    if (embedded) {
        return { ...embedded, filename: fileName };
    }
    try {
        const url = `${backendUrl()}/get?fileName=${encodeURIComponent(fileName)}`;
        console.log(`Fetching ${url}`);
        const _token = getToken();

        try {
            const viaArrow = await fetchArtifactAsArrow(url, _token);
            if (viaArrow) {
                return viaArrow;
            }
        } catch (arrowError: unknown) {
            // A decode fault must not cost the user their data: fall through
            // to the format that has always worked, and say so once.
            console.warn(
                "Arrow artifact fetch failed, falling back to JSON:",
                arrowError instanceof Error ? arrowError.message : String(arrowError),
            );
        }

        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...(_token ? { 'Authorization': `Bearer ${_token}` } : {}),
            },
        });

        if (!response.ok) {
            throw new Error(`Failed to fetch file ${url}: ${response.statusText}`);
        }

        const jsonData = await response.json();

        console.log(`Fetched data`, jsonData);

        return jsonData;
    } catch (error: unknown) {
        console.error("Error:", error instanceof Error ? error.message : String(error));
        throw error;
    }
}

/**
 * Fetches a preview version of the data (first 100 rows) for display purposes.
 * This is more efficient than fetching the entire dataset when only displaying data.
 * 
 * @param fileName - The name of the file to fetch
 * @returns The preview data with metadata about row counts
 */
export async function fetchPreviewData(fileName: string) {
    // The Data Pool tile reads its preview through here rather than through
    // `fetchData`, so a standalone page has to answer here too or a pool tile
    // is the one thing on it that still calls out.
    const embedded = embeddedArtifact(fileName);
    if (embedded) {
        return previewOfEmbedded(fileName, embedded);
    }
    try {
        // Use the correct backend URL
        const base = backendUrl() || 'http://localhost:5002';
        const url = `${base}/get-preview?fileName=${encodeURIComponent(fileName)}`;
        console.log(`[fetchPreviewData] Fetching preview from ${url}`);
        const _token = getToken();
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...(_token ? { 'Authorization': `Bearer ${_token}` } : {}),
            },
        });

        if (!response.ok) {
            throw new Error(`Failed to fetch preview ${url}: ${response.statusText}`);
        }

        const jsonData = await response.json();
        console.log(`[fetchPreviewData] Fetched preview data:`, jsonData);

        return jsonData;
    } catch (error: unknown) {
        console.error("[fetchPreviewData] Error:", error instanceof Error ? error.message : String(error));
        throw error;
    }
}

/** The header the raster route describes the raster in, as JSON. */
export const RASTER_META_HEADER = "X-Curio-Raster";

export type FetchedRaster =
    | { ok: true; bytes: ArrayBuffer; meta: any }
    | { ok: false; status: number; meta?: any; message: string };

/**
 * A raster artifact's GeoTIFF bytes, for an Autark node to load, and what the
 * sandbox read of it (size, CRS, transform) in the `X-Curio-Raster` header.
 * `part` picks one raster out of a Python tuple. A raster larger than
 * `maxCells` cells or `maxSide` on a side is not sent at all: the answer is a
 * 413 with its size, so nothing that large is downloaded only to be refused.
 */
export async function fetchRaster(
    fileName: string,
    opts: { part?: number; maxCells: number; maxSide: number },
): Promise<FetchedRaster> {
    const params = new URLSearchParams({
        fileName,
        maxCells: String(opts.maxCells),
        maxSide: String(opts.maxSide),
    });
    if (opts.part != null) params.set("part", String(opts.part));
    const token = getToken();
    const response = await fetch(`${backendUrl()}/raster?${params.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) {
        let body: any = null;
        try {
            body = await response.json();
        } catch {
            body = null;
        }
        return {
            ok: false,
            status: response.status,
            meta: body?.meta,
            message: typeof body?.message === "string" ? body.message : `HTTP ${response.status}`,
        };
    }
    const header = response.headers.get(RASTER_META_HEADER);
    let meta: any = null;
    try {
        meta = header ? JSON.parse(header) : null;
    } catch {
        meta = null;
    }
    if (!meta) {
        return { ok: false, status: response.status, message: "the raster came without its description" };
    }
    return { ok: true, bytes: await response.arrayBuffer(), meta };
}
