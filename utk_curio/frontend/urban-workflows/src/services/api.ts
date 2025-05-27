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
    } catch (error) {
        console.error("Error:", error.message);
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