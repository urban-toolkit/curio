import { getToken } from "../utils/authApi";
import { backendUrl } from "../utils/backendUrl";

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
    return tableToEnvelope(table, headers);
}

export async function fetchData(fileName: string) {
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
