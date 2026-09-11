import { getToken } from "../utils/authApi";
import { backendUrl } from "../utils/backendUrl";

export async function fetchData(fileName: string) {
    try {
        const url = `${backendUrl()}/get?fileName=${encodeURIComponent(fileName)}`;
        console.log(`Fetching ${url}`);
        const _token = getToken();
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
