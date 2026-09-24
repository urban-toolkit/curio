/**
 * `fetchData` asks for Arrow and falls back to JSON without the caller knowing.
 *
 * The fallback is the whole safety story of this change: the sandbox serves
 * Arrow only for tabular kinds, refuses geometry until the client can decode
 * WKB, and a decode fault must cost a log line rather than the user's data.
 */
import { tableFromArrays, tableToIPC } from "apache-arrow";

import { ARROW_IPC_MIME, fetchData } from "../../services/api";

jest.mock("../../utils/authApi", () => ({ getToken: () => "test-token" }));
jest.mock("../../utils/backendUrl", () => ({ backendUrl: () => "http://backend" }));

const JSON_ENVELOPE = { data: { n: [1, 2] }, dataType: "dataframe", filename: "a1" };

function arrowResponse() {
    const ipc = tableToIPC(tableFromArrays({ n: Int32Array.from([1, 2]) }));
    return {
        ok: true,
        status: 200,
        headers: new Headers({
            "Content-Type": ARROW_IPC_MIME,
            "X-Curio-Kind": "dataframe",
            "X-Curio-Filename": "a1",
        }),
        arrayBuffer: async () => ipc.buffer.slice(ipc.byteOffset, ipc.byteOffset + ipc.byteLength),
    };
}

function jsonResponse() {
    return {
        ok: true,
        status: 200,
        headers: new Headers({ "Content-Type": "application/json" }),
        json: async () => JSON_ENVELOPE,
    };
}

function unsupportedMediaType() {
    return {
        ok: false,
        status: 415,
        headers: new Headers({ "Content-Type": "application/json" }),
        json: async () => ({ error: "not_acceptable" }),
    };
}

describe("fetchData", () => {
    let warn: jest.SpyInstance;

    beforeEach(() => {
        jest.spyOn(console, "log").mockImplementation(() => {});
        warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    });

    afterEach(() => {
        jest.restoreAllMocks();
        delete (global as any).fetch;
    });

    it("asks for Arrow first and returns the decoded envelope", async () => {
        const fetchMock = jest.fn().mockResolvedValue(arrowResponse());
        (global as any).fetch = fetchMock;

        const result = await fetchData("a1");

        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [, init] = fetchMock.mock.calls[0];
        expect(init.headers.Accept).toBe(ARROW_IPC_MIME);
        expect(result.dataType).toBe("dataframe");
        expect(Array.from(result.data.n)).toEqual([1, 2]);
    });

    it("falls back to JSON when the sandbox refuses the format", async () => {
        // 415 is an ordinary answer: a dict, a list, a raster, or geometry
        // without the opt-in. The user must still get their artifact.
        const fetchMock = jest
            .fn()
            .mockResolvedValueOnce(unsupportedMediaType())
            .mockResolvedValueOnce(jsonResponse());
        (global as any).fetch = fetchMock;

        const result = await fetchData("a1");

        expect(fetchMock).toHaveBeenCalledTimes(2);
        expect(result).toEqual(JSON_ENVELOPE);
    });

    it("falls back when the response is not actually Arrow", async () => {
        const notArrow = { ...jsonResponse() };
        const fetchMock = jest
            .fn()
            .mockResolvedValueOnce(notArrow)
            .mockResolvedValueOnce(jsonResponse());
        (global as any).fetch = fetchMock;

        expect(await fetchData("a1")).toEqual(JSON_ENVELOPE);
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it("falls back, loudly, when decoding throws", async () => {
        const corrupt = {
            ...arrowResponse(),
            arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer,
        };
        const fetchMock = jest
            .fn()
            .mockResolvedValueOnce(corrupt)
            .mockResolvedValueOnce(jsonResponse());
        (global as any).fetch = fetchMock;

        expect(await fetchData("a1")).toEqual(JSON_ENVELOPE);
        expect(warn).toHaveBeenCalled();
    });

    it("still throws when the JSON fallback itself fails", async () => {
        const fetchMock = jest
            .fn()
            .mockResolvedValueOnce(unsupportedMediaType())
            .mockResolvedValueOnce({ ok: false, statusText: "Not Found", headers: new Headers() });
        (global as any).fetch = fetchMock;

        await expect(fetchData("a1")).rejects.toThrow("Not Found");
    });
});
