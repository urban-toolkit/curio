/**
 * The Arrow adapter has to produce the envelope the canvas already reads.
 *
 * Four of these exist because a prototype against real artifacts caught the
 * failure: Arrow keeps int64 as BigInt, and `JSON.stringify` throws on a
 * BigInt, so the data export node would have broken on contact with a plain
 * pass-through. The rest pin the differences between the two encodings that
 * are invisible until a chart renders wrong.
 */
import { tableFromArrays, tableToIPC, tableFromIPC } from "apache-arrow";

import { tableToEnvelope } from "../../services/arrowEnvelope";

function roundTrip(arrays: Record<string, any>) {
    return tableFromIPC(tableToIPC(tableFromArrays(arrays)));
}

const HEADERS = {
    "X-Curio-Kind": "dataframe",
    "X-Curio-Filename": "1790201370084_b973a38f",
};

describe("tableToEnvelope", () => {
    it("produces the column-major shape the consumers index into", () => {
        const table = roundTrip({
            n: Int32Array.from([1, 2, 3]),
            value: Float64Array.from([1.5, 2.5, 3.5]),
        });

        const envelope = tableToEnvelope(table, HEADERS);

        expect(envelope.dataType).toBe("dataframe");
        expect(envelope.filename).toBe("1790201370084_b973a38f");
        expect(Object.keys(envelope.data).sort()).toEqual(["n", "value"]);
        expect(Array.from(envelope.data.n)).toEqual([1, 2, 3]);
        expect(envelope.data.value[2]).toBe(3.5);
    });

    it("converts int64 columns to numbers rather than BigInt", () => {
        // JSON.stringify throws on a BigInt, and dataExportBehavior calls it.
        const table = roundTrip({ big: BigInt64Array.from([1n, 2n]) });

        const envelope = tableToEnvelope(table, HEADERS);

        expect(typeof envelope.data.big[0]).toBe("number");
        expect(envelope.data.big).toEqual([1, 2]);
        expect(() => JSON.stringify(envelope)).not.toThrow();
    });

    it("maps non-finite floats to null, as the JSON path does", () => {
        // normalize_dataframe_for_json scrubs these; Arrow carries them.
        // Without the mapping a chart gets NaN where it used to get a gap.
        const table = roundTrip({
            v: Float64Array.from([1.5, NaN, Infinity, -Infinity]),
        });

        const envelope = tableToEnvelope(table, HEADERS);

        expect(envelope.data.v).toEqual([1.5, null, null, null]);
    });

    it("parses the columns the server says are JSON-encoded", () => {
        const table = roundTrip({ tags: ['{"a":1}', '{"b":2}'] });

        const envelope = tableToEnvelope(table, {
            ...HEADERS,
            "X-Curio-Encoded-Object-Columns": "tags",
        });

        expect(envelope.data.tags).toEqual([{ a: 1 }, { b: 2 }]);
    });

    it("leaves an encoded column alone when its value is not JSON", () => {
        const table = roundTrip({ tags: ["not json"] });

        const envelope = tableToEnvelope(table, {
            ...HEADERS,
            "X-Curio-Encoded-Object-Columns": "tags",
        });

        expect(envelope.data.tags).toEqual(["not json"]);
    });

    it("carries the schema the JSON envelope sends as `schema`", () => {
        // vegaBehavior reads this to choose a starter spec.
        const table = roundTrip({ n: Int32Array.from([1]) });

        const envelope = tableToEnvelope(table, {
            ...HEADERS,
            "X-Curio-Schema": '{"n":"int32"}',
        });

        expect(envelope.schema).toEqual({ n: "int32" });
    });

    it("survives a malformed schema header without losing the data", () => {
        const table = roundTrip({ n: Int32Array.from([1]) });

        const envelope = tableToEnvelope(table, {
            ...HEADERS,
            "X-Curio-Schema": "{not json",
        });

        expect(envelope.schema).toBeUndefined();
        expect(envelope.data.n).toBeDefined();
    });

    it("carries the preview counts when the response is a preview", () => {
        const table = roundTrip({ n: Int32Array.from([1]) });

        const envelope = tableToEnvelope(table, {
            ...HEADERS,
            "X-Curio-Preview": "true",
            "X-Curio-Preview-Rows": "100",
            "X-Curio-Total-Rows": "5000",
        });

        expect(envelope.preview).toBe(true);
        expect(envelope.previewRows).toBe(100);
        expect(envelope.totalRows).toBe(5000);
    });

    it("reads headers case-insensitively", () => {
        // fetch() lowercases header names; a raw dict may not.
        const table = roundTrip({ n: Int32Array.from([1]) });

        const envelope = tableToEnvelope(table, {
            "x-curio-kind": "dataframe",
            "x-curio-filename": "abc",
        });

        expect(envelope.dataType).toBe("dataframe");
        expect(envelope.filename).toBe("abc");
    });
});
