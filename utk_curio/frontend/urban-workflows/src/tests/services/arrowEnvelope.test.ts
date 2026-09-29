/**
 * The Arrow adapter has to produce the envelope the canvas already reads.
 *
 * Four of these exist because a prototype against real artifacts caught the
 * failure: Arrow keeps int64 as BigInt, and `JSON.stringify` throws on a
 * BigInt, so the data export node would have broken on contact with a plain
 * pass-through. The rest pin the differences between the two encodings that
 * are invisible until a chart renders wrong.
 */
import {
    DateDay,
    makeData,
    makeVector,
    Table,
    tableFromArrays,
    tableFromIPC,
    tableToIPC,
    TimestampMicrosecond,
    TimestampNanosecond,
    TimestampSecond,
} from "apache-arrow";

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

describe("tableToEnvelope, dates and timestamps", () => {
    // The strings the JSON path sends for the same cells, from isoformat() in
    // sandbox/util/codec.py; test_arrow_artifact_route.py pins that side.
    // Arrow's own `get` returns epoch milliseconds, which Simple View, the
    // Data Pool and Vega tooltips printed as a bare number (#523).

    function column(type: any, data: Int32Array | BigInt64Array, valid: boolean[]) {
        const nullBitmap = new Uint8Array(Math.ceil(valid.length / 8));
        valid.forEach((ok, i) => {
            if (ok) nullBitmap[i >> 3] |= 1 << (i & 7);
        });
        return makeVector(makeData({
            type,
            length: valid.length,
            nullCount: valid.filter((ok) => !ok).length,
            nullBitmap,
            data,
        } as any));
    }

    function envelopeOf(columns: Record<string, any>) {
        return tableToEnvelope(tableFromIPC(tableToIPC(new Table(columns))), HEADERS);
    }

    it("sends a date as YYYY-MM-DD and a missing one as null", () => {
        const envelope = envelopeOf({
            day: column(new DateDay(), Int32Array.from([19844, 0, -1]), [true, false, true]),
        });

        expect(envelope.data.day).toEqual(["2024-05-01", null, "1969-12-31"]);
    });

    it("sends a timestamp as isoformat does, and a missing one as NaT", () => {
        const envelope = envelopeOf({
            naive: column(
                new TimestampMicrosecond(),
                BigInt64Array.from([1714521600000000n, 0n, 1714566645123456n]),
                [true, false, true],
            ),
        });

        expect(envelope.data.naive).toEqual([
            "2024-05-01T00:00:00", "NaT", "2024-05-01T12:30:45.123456",
        ]);
    });

    it("adds the offset for a column with a time zone", () => {
        // DuckDB stores every zoned column as UTC; a GeoDataFrame keeps its zone.
        const envelope = envelopeOf({
            utc: column(
                new TimestampMicrosecond("UTC"),
                BigInt64Array.from([1714521600000000n, 1714566645000000n]),
                [true, true],
            ),
            chicago: column(
                new TimestampSecond("America/Chicago"),
                BigInt64Array.from([1714539600n, 1705327200n]),
                [true, true],
            ),
        });

        expect(envelope.data.utc).toEqual([
            "2024-05-01T00:00:00+00:00", "2024-05-01T12:30:45+00:00",
        ]);
        expect(envelope.data.chicago).toEqual([
            "2024-05-01T00:00:00-05:00", "2024-01-15T08:00:00-06:00",
        ]);
    });

    it("keeps nanoseconds, and a fraction before 1970", () => {
        const envelope = envelopeOf({
            nanos: column(
                new TimestampNanosecond(),
                BigInt64Array.from([1714521600000000001n]),
                [true],
            ),
            early: column(new TimestampMicrosecond(), BigInt64Array.from([-500000n]), [true]),
        });

        expect(envelope.data.nanos).toEqual(["2024-05-01T00:00:00.000000001"]);
        expect(envelope.data.early).toEqual(["1969-12-31T23:59:59.500000"]);
        expect(() => JSON.stringify(envelope)).not.toThrow();
    });
});

describe("tableToEnvelope, geodataframe", () => {
    // A real artifact from the real code path: a GeoDataFrame saved through
    // parsers.save_to_duckdb and read back both ways, so this compares the
    // adapter against the exact envelope the JSON path would have sent.
    // Generated by scripts/generate_arrow_fixture.py.
    const fixture = require("../fixtures/arrow-geodataframe.json");

    function decode() {
        const bytes = Uint8Array.from(atob(fixture.arrow_base64), (c) => c.charCodeAt(0));
        return tableToEnvelope(tableFromIPC(bytes), fixture.headers);
    }

    it("rebuilds the FeatureCollection the JSON path sends", () => {
        const envelope = decode();
        const expected = fixture.json_envelope;

        expect(envelope.dataType).toBe("geodataframe");
        expect(envelope.data.type).toBe("FeatureCollection");
        expect(envelope.data.features).toHaveLength(expected.data.features.length);
    });

    it("decodes every geometry to what geopandas serialised", () => {
        const envelope = decode();

        envelope.data.features.forEach((feature: any, i: number) => {
            expect(feature.geometry).toEqual(
                fixture.json_envelope.data.features[i].geometry,
            );
        });
    });

    it("keeps the properties, minus the geometry column", () => {
        const envelope = decode();

        envelope.data.features.forEach((feature: any, i: number) => {
            expect(feature.properties).toEqual(
                fixture.json_envelope.data.features[i].properties,
            );
        });
    });

    it("carries the CRS urn and the geometry name the canvas reads", () => {
        // activeGeometryName reads geometry_name; geoCrs reads the urn. Losing
        // either renders a map in the wrong projection, or not at all.
        const envelope = decode();

        expect(envelope.data.crs).toEqual(fixture.json_envelope.data.crs);
        expect(envelope.data.geometry_name).toBe(
            fixture.json_envelope.data.geometry_name,
        );
    });

    it("carries the schema the JSON envelope sends", () => {
        expect(decode().schema).toEqual(fixture.json_envelope.schema);
    });

    it("decodes a SECOND geometry column too, not just the active one", () => {
        // `gdf["bbox"] = gdf.geometry.envelope` is in the shipped examples.
        // Every geometry column is WKB in GeoParquet, and the JSON path puts
        // the secondary ones in `properties` as GeoJSON. Passing one through
        // raw yielded a byte-indexed object where a chart wanted a geometry,
        // and vega-lite rendered a blank canvas with no error at all
        // (14-vega-lite-crs-and-geometry-types).
        const envelope = decode();

        envelope.data.features.forEach((feature: any, i: number) => {
            const expected = fixture.json_envelope.data.features[i].properties.bbox;
            expect(feature.properties.bbox).toEqual(expected);
            // A geometry object, not the raw bytes. (The type varies: the
            // envelope of a Point is a Point, of a LineString a Polygon.)
            expect(typeof feature.properties.bbox.type).toBe("string");
            expect(feature.properties.bbox.coordinates).toBeDefined();
        });
    });
});
