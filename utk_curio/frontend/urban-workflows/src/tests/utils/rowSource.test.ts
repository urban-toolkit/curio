/**
 * One flattener for five call sites, and it only builds what is read.
 *
 * The laziness is the point: the Data Pool renders 100 preview rows and falls
 * back to the full table only when there is no preview, so flattening a
 * 200k-row artifact to show 100 rows cost 149.8ms against 0.5ms for the page.
 * These pin both halves -- that lazy and eager agree exactly, and that lazy
 * really does skip the rows nobody asked for.
 */
import { lazyRows, toRows } from "../../utils/rowSource";

const DATAFRAME = {
    dataType: "dataframe",
    data: {
        id: [1, 2, 3],
        name: ["a", "b", "c"],
        value: [1.5, 2.5, 3.5],
    },
};

const INDEX_KEYED = {
    dataType: "dataframe",
    data: {
        id: { "0": 1, "1": 2 },
        name: { "0": "a", "1": "b" },
    },
};

const GEODATAFRAME = {
    dataType: "geodataframe",
    data: {
        type: "FeatureCollection",
        features: [
            { type: "Feature", properties: { id: 1, name: "a" }, geometry: null },
            { type: "Feature", properties: { id: 2, name: "b" }, geometry: null },
        ],
    },
};

/** A payload that records which columns were actually read. */
function counting(payload: any) {
    const reads: string[] = [];
    const data = new Proxy(payload.data, {
        get(target, property) {
            if (typeof property === "string" && property in target) reads.push(property);
            return (target as any)[property];
        },
    });
    return { payload: { ...payload, data }, reads };
}

describe("rowSource", () => {
    it.each([
        ["dataframe", DATAFRAME],
        ["index-keyed dataframe", INDEX_KEYED],
        ["geodataframe", GEODATAFRAME],
    ])("lazy and eager agree for a %s", (_label, payload) => {
        expect(lazyRows(payload).slice(0)).toEqual(toRows(payload));
    });

    it("produces the row shape the five call sites produced before", () => {
        expect(toRows(DATAFRAME)).toEqual([
            { id: 1, name: "a", value: 1.5 },
            { id: 2, name: "b", value: 2.5 },
            { id: 3, name: "c", value: 3.5 },
        ]);
    });

    it("drops the geometry and keeps the properties, as the table wants", () => {
        expect(toRows(GEODATAFRAME)).toEqual([
            { id: 1, name: "a" },
            { id: 2, name: "b" },
        ]);
    });

    it("only touches the rows that are read", () => {
        // The claim the laziness rests on. Reading a page of a large artifact
        // must not walk the rest of it.
        const { payload, reads } = counting(DATAFRAME);
        const rows = lazyRows(payload);

        const before = reads.length;
        const page = rows.slice(0, 1);

        expect(page).toHaveLength(1);
        // Three columns for one row, not three columns times three rows.
        expect(reads.length - before).toBe(3);
    });

    it("remembers a row once it has been built", () => {
        const { payload, reads } = counting(DATAFRAME);
        const rows = lazyRows(payload);

        rows[0];
        const afterFirst = reads.length;
        rows[0];

        expect(reads.length).toBe(afterFirst);
    });

    it("supports what the table path does to it", () => {
        // TabularPreviewTable: rows.slice(0, maxRows), then length/map/[0].
        const rows = lazyRows(DATAFRAME);

        expect(rows.length).toBe(3);
        expect(rows[1]).toEqual({ id: 2, name: "b", value: 2.5 });
        expect(rows.slice(0, 2)).toHaveLength(2);
        expect(rows.map((row) => row.id)).toEqual([1, 2, 3]);
        expect(rows.filter((row) => (row.id as number) > 1)).toHaveLength(2);
        expect([...rows]).toHaveLength(3);
    });

    it("passes Array.isArray, because two call sites gate on it", () => {
        // vegaGeoSpec and imageColumns both do `Array.isArray(rows) ? ... : []`,
        // so a lazy source that failed this would silently drop the data
        // rather than break loudly. It passes because the proxy's target is a
        // real array, which Array.isArray looks through -- a property worth
        // pinning, since swapping the target for `{}` would still typecheck.
        expect(Array.isArray(lazyRows(DATAFRAME))).toBe(true);
    });

    it("clamps a slice the way an array does", () => {
        const rows = lazyRows(DATAFRAME);

        expect(rows.slice(0, 99)).toHaveLength(3);
        expect(rows.slice(2, 1)).toHaveLength(0);
        expect(rows.slice(-1)).toEqual([{ id: 3, name: "c", value: 3.5 }]);
    });

    it("returns nothing for the empty shapes", () => {
        for (const payload of [
            null,
            undefined,
            {},
            { dataType: "dataframe", data: {} },
            { dataType: "geodataframe", data: { type: "FeatureCollection", features: [] } },
        ] as any[]) {
            expect(toRows(payload)).toEqual([]);
            expect(lazyRows(payload).length).toBe(0);
        }
    });
});
