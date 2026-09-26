/**
 * One way to turn an artifact payload into rows, lazily.
 *
 * Five near-identical flatteners had grown up around this: `createTableData`
 * (useTableData), `buildTableRows` (simpleVisBehavior), `rowsFromParseOutput`
 * (tabularPreview), `rowsFromColumns` (vegaBehavior) and `parseDataframe`
 * (parsing). They all read the same two shapes -- a dataframe's column-major
 * object, or a geodataframe's FeatureCollection -- and they all built every
 * row up front.
 *
 * Building every row up front is the expensive part, and usually wasted. The
 * Data Pool renders 100 preview rows from `/get-preview` and falls back to the
 * full table only when there is no preview, so a 200k-row artifact produced
 * 200k row objects to show 100 of them: 149.8ms, against 0.5ms for the page
 * that was actually read.
 *
 * So `lazyRows` builds a row when something asks for it and remembers it.
 * `toRows` is the eager spelling, for callers that hand the result to
 * something that needs a real array (vega-lite's `values`, for instance).
 */

export type Row = Record<string, unknown>;

export type PayloadLike = {
    dataType?: string;
    data?: any;
} | null | undefined;

/** Column names and a row count, for either payload shape. */
function describe(payload: PayloadLike): {
    columns: string[];
    length: number;
    cellAt: (column: string, index: number) => unknown;
} | null {
    const data = payload?.data;
    if (!data || typeof data !== "object") return null;

    if (payload?.dataType === "geodataframe") {
        const features: any[] = Array.isArray(data.features) ? data.features : [];
        if (features.length === 0) return null;
        return {
            columns: Object.keys(features[0]?.properties || {}),
            length: features.length,
            cellAt: (column, index) => features[index]?.properties?.[column],
        };
    }

    const columns = Object.keys(data);
    if (columns.length === 0) return null;
    const first = data[columns[0]];
    // parseOutput sends column-major arrays, but a payload that has been
    // through JSON with integer keys arrives as an index-keyed object, and
    // both spellings have always been accepted here.
    const length = Array.isArray(first)
        ? first.length
        : first && typeof first === "object"
          ? Object.keys(first).length
          : 0;
    return {
        columns,
        length,
        cellAt: (column, index) => {
            const columnData = data[column];
            if (Array.isArray(columnData)) return columnData[index];
            if (columnData && typeof columnData === "object") {
                return (columnData as Record<string, unknown>)[String(index)];
            }
            return null;
        },
    };
}

/**
 * Rows that exist once something reads them.
 *
 * Presents the slice of the array API these consumers actually use --
 * `length`, indexing, `slice`, `map` and iteration -- which is what the table
 * path needs (`rows.slice(0, maxRows)` and then ordinary array work). It is
 * deliberately not an Array subclass: the point is to not have built the
 * elements, and there is no way to do that and still be one.
 */
export function lazyRows(payload: PayloadLike): Row[] {
    const described = describe(payload);
    if (!described) return [];
    const { columns, length, cellAt } = described;
    const cache: Row[] = new Array(length);

    const build = (index: number): Row => {
        let row = cache[index];
        if (row === undefined) {
            row = {};
            for (const column of columns) row[column] = cellAt(column, index);
            cache[index] = row;
        }
        return row;
    };

    const slice = (from = 0, to = length): Row[] => {
        const start = from < 0 ? Math.max(length + from, 0) : Math.min(from, length);
        const end = to < 0 ? Math.max(length + to, 0) : Math.min(to, length);
        const out: Row[] = [];
        for (let i = start; i < end; i++) out.push(build(i));
        return out;
    };

    const handler: ProxyHandler<Row[]> = {
        get(_target, property) {
            if (property === "length") return length;
            if (property === "slice") return slice;
            if (property === "map") {
                return (fn: (row: Row, index: number) => unknown) => {
                    const out = new Array(length);
                    for (let i = 0; i < length; i++) out[i] = fn(build(i), i);
                    return out;
                };
            }
            if (property === "filter") {
                return (fn: (row: Row, index: number) => boolean) => {
                    const out: Row[] = [];
                    for (let i = 0; i < length; i++) {
                        const row = build(i);
                        if (fn(row, i)) out.push(row);
                    }
                    return out;
                };
            }
            if (property === "forEach") {
                return (fn: (row: Row, index: number) => void) => {
                    for (let i = 0; i < length; i++) fn(build(i), i);
                };
            }
            if (property === Symbol.iterator) {
                return function* () {
                    for (let i = 0; i < length; i++) yield build(i);
                };
            }
            if (typeof property === "string" && /^\d+$/.test(property)) {
                const index = Number(property);
                return index < length ? build(index) : undefined;
            }
            return undefined;
        },
        has(_target, property) {
            if (property === "length") return true;
            return typeof property === "string" && /^\d+$/.test(property)
                && Number(property) < length;
        },
        ownKeys() {
            const keys = new Array(length);
            for (let i = 0; i < length; i++) keys[i] = String(i);
            keys.push("length");
            return keys;
        },
        getOwnPropertyDescriptor(_target, property) {
            if (property === "length") {
                return { value: length, writable: false, enumerable: false, configurable: true };
            }
            return { enumerable: true, configurable: true, value: build(Number(property)) };
        },
    };

    return new Proxy([] as Row[], handler);
}

/** Every row, built now. For callers that need a genuine array. */
export function toRows(payload: PayloadLike): Row[] {
    const described = describe(payload);
    if (!described) return [];
    const { columns, length, cellAt } = described;
    const rows: Row[] = new Array(length);
    for (let i = 0; i < length; i++) {
        const row: Row = {};
        for (const column of columns) row[column] = cellAt(column, i);
        rows[i] = row;
    }
    return rows;
}
