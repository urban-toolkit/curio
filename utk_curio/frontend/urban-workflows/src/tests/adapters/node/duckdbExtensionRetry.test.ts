/**
 * Surviving a failed DuckDB spatial-extension fetch (#318).
 *
 * autk-db's `init()` runs `INSTALL spatial; LOAD spatial;`, which downloads the
 * extension from extensions.duckdb.org into every fresh in-browser DuckDB. A
 * node that runs the grammar therefore depends on a network fetch it never
 * asked for, and one flake failed the whole node:
 *
 *     Failed to execute 'send' on 'XMLHttpRequest': Failed to load
 *     'https://extensions.duckdb.org/v1.5.1/wasm_eh/spatial.duckdb_extension.wasm'
 *
 * A retry needs a FRESH instance, not another call on the same one: the worker
 * that failed to load the extension keeps that state.
 */
import {
  isExtensionLoadError,
  withExtensionRetry,
} from "../../../adapters/node/duckdbExtensionRetry";

const EXTENSION_ERROR = new Error(
  "Failed to execute 'send' on 'XMLHttpRequest': Failed to load "
  + "'https://extensions.duckdb.org/v1.5.1/wasm_eh/spatial.duckdb_extension.wasm'.",
);

describe("isExtensionLoadError", () => {
  it("recognises the extension fetch failure", () => {
    expect(isExtensionLoadError(EXTENSION_ERROR)).toBe(true);
    expect(isExtensionLoadError(new Error("failed to load spatial.duckdb_extension.wasm"))).toBe(true);
  });

  it("does not claim an ordinary failure", () => {
    expect(isExtensionLoadError(new Error("Binder Error: no such column"))).toBe(false);
    expect(isExtensionLoadError(undefined)).toBe(false);
    expect(isExtensionLoadError("extensions.duckdb.org")).toBe(true);
  });
});

describe("withExtensionRetry", () => {
  it("retries the extension failure and returns the later success", async () => {
    const make = jest.fn()
      .mockRejectedValueOnce(EXTENSION_ERROR)
      .mockResolvedValueOnce("second instance");

    await expect(withExtensionRetry(make, { delaysMs: [0, 0] })).resolves.toBe("second instance");
    expect(make).toHaveBeenCalledTimes(2);
  });

  it("builds a fresh instance per attempt", async () => {
    const built: number[] = [];
    let n = 0;
    const make = jest.fn(async () => {
      n += 1;
      built.push(n);
      if (n < 3) throw EXTENSION_ERROR;
      return n;
    });

    await expect(withExtensionRetry(make, { delaysMs: [0, 0] })).resolves.toBe(3);
    expect(built).toEqual([1, 2, 3]);
  });

  it("gives up after the last attempt and rethrows that failure", async () => {
    const make = jest.fn().mockRejectedValue(EXTENSION_ERROR);

    await expect(withExtensionRetry(make, { delaysMs: [0, 0] })).rejects.toThrow(/extensions\.duckdb\.org/);
    expect(make).toHaveBeenCalledTimes(3);
  });

  it("never retries an ordinary failure - it would just be slower", async () => {
    const make = jest.fn().mockRejectedValue(new Error("Binder Error: no such column"));

    await expect(withExtensionRetry(make, { delaysMs: [0, 0] })).rejects.toThrow("Binder Error: no such column");
    expect(make).toHaveBeenCalledTimes(1);
  });
});
