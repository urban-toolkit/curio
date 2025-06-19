export async function fetchData(fileName: string, vega: boolean = false) {
    try {
        // const url = `${process.env.BACKEND_URL}/get?fileName=${encodeURIComponent(fileName)}${vega ? '&vega=true' : ''}`;
        const url = `${process.env.BACKEND_URL}/get?fileName=${encodeURIComponent(fileName)}`;
        console.log(`Fetching ${url}`);
        
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
            },
        });

        if (!response.ok) {
            throw new Error(`Failed to fetch file ${url}: ${response.statusText}`);
        }

        const jsonData = await response.json();

        if(vega)
            return transformToVega(jsonData);

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
        const backendUrl = process.env.BACKEND_URL || 'http://localhost:5002';
        const url = `${backendUrl}/get-preview?fileName=${encodeURIComponent(fileName)}`;
        console.log(`[fetchPreviewData] Fetching preview from ${url}`);
        
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
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

/**
 * Transforms a pandas-style JSON (column-based) to Vega-Lite-ready JSON (row-based).
 *
 * @param data - The original pandas-style JSON data.
 * @returns The transformed Vega-Lite-ready JSON data.
 */
export function transformToVega(
    data: { data?: Record<string, any[]> }
): Record<string, any>[] | typeof data {
    if (data.data && typeof data.data === "object" && !Array.isArray(data.data)) {
        const columns = Object.keys(data.data);
        const numRows = data.data[columns[0]]?.length || 0;

        const values: Record<string, any>[] = [];

        for (let i = 0; i < numRows; i++) {
            const row: Record<string, any> = {};
            for (const col of columns) {
                row[col] = data.data[col][i];
            }
            values.push(row);
        }

        return values;
    }

    return data;
}