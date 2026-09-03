/**
 * The WebGPU probe answers the question Firefox actually poses (#272).
 *
 * Firefox with `dom.webgpu.enabled` on, verified working by third-party
 * checkers, was still told by Curio that it had no WebGPU. The probe asked
 * `requestAdapter()` once, took the `null` Firefox returns while its GPU
 * process is still starting, and memoised that answer for the life of the
 * page. Every case here is one of the ways that single-shot, cache-forever
 * probe was wrong.
 */
import {
  detectWebGpuSupport,
  reprobeWebGpuSupport,
  WEBGPU_ADAPTER_RETRY_DELAY_MS,
  WEBGPU_PROBE_TIMEOUT_MS,
  __resetWebGpuSupportCache,
} from "../../utils/webgpuSupport";

const ADAPTER = { name: "fake-adapter" };

function installGpu(gpu: unknown) {
  Object.defineProperty(navigator, "gpu", { configurable: true, value: gpu });
}

function gpuWith(requestAdapter: jest.Mock, extra: Record<string, unknown> = {}) {
  installGpu({ requestAdapter, getPreferredCanvasFormat: () => "bgra8unorm", ...extra });
  return requestAdapter;
}

function setSecureContext(value: boolean | undefined) {
  Object.defineProperty(window, "isSecureContext", { configurable: true, value });
}

/** Resolve the probe under fake timers: flush microtasks, advance, repeat. */
async function settle<T>(promise: Promise<T>, advanceMs: number): Promise<T> {
  // Let the first requestAdapter() resolve and the retry timer be armed.
  await Promise.resolve();
  await Promise.resolve();
  jest.advanceTimersByTime(advanceMs);
  return promise;
}

beforeEach(() => {
  jest.useFakeTimers();
  __resetWebGpuSupportCache();
  setSecureContext(true);
  installGpu(undefined);
});

afterEach(() => {
  jest.useRealTimers();
});

describe("detectWebGpuSupport", () => {
  test("Firefox: null on the first requestAdapter, an adapter 150 ms later → supported", async () => {
    const requestAdapter = gpuWith(
      jest.fn().mockResolvedValueOnce(null).mockResolvedValueOnce(ADAPTER),
    );

    const result = await settle(detectWebGpuSupport(), WEBGPU_ADAPTER_RETRY_DELAY_MS);

    expect(result.supported).toBe(true);
    expect(requestAdapter).toHaveBeenCalledTimes(2);
  });

  test("null twice is a missing adapter, and says to check again", async () => {
    gpuWith(jest.fn().mockResolvedValue(null));

    const result = await settle(detectWebGpuSupport(), WEBGPU_ADAPTER_RETRY_DELAY_MS);

    expect(result.supported).toBe(false);
    expect(result.reasonCode).toBe("no-adapter");
    expect(result.reason).toMatch(/Check again/);
  });

  test("a rejecting requestAdapter is reported as the failure it is, with its message", async () => {
    gpuWith(jest.fn().mockRejectedValue(new Error("device lost")));

    const result = await detectWebGpuSupport();

    expect(result.reasonCode).toBe("request-failed");
    expect(result.reason).toContain("device lost");
    // Not the "enable dom.webgpu.enabled" copy: the pref is evidently on.
    expect(result.reason).not.toMatch(/about:config/);
  });

  test("a requestAdapter that never answers times out instead of holding the run", async () => {
    gpuWith(jest.fn(() => new Promise(() => undefined)));

    const pending = detectWebGpuSupport();
    await Promise.resolve();
    jest.advanceTimersByTime(WEBGPU_PROBE_TIMEOUT_MS + 1);
    const result = await pending;

    expect(result.reasonCode).toBe("timed-out");
    expect(result.reason).toMatch(/Check again/);
  });

  test("no navigator.gpu on an insecure page blames the page, not the browser", async () => {
    setSecureContext(false);
    installGpu(undefined);

    const result = await detectWebGpuSupport();

    expect(result.reasonCode).toBe("insecure-context");
    expect(result.reason).toMatch(/https|localhost/);
  });

  test("no navigator.gpu on a secure page is a browser without the API", async () => {
    const result = await detectWebGpuSupport();

    expect(result.reasonCode).toBe("no-api");
    expect(result.reason).toMatch(/dom\.webgpu\.enabled/);
  });

  test("a gpu object without getPreferredCanvasFormat is incomplete, which autk-map cannot use", async () => {
    installGpu({ requestAdapter: jest.fn().mockResolvedValue(ADAPTER) });

    const result = await detectWebGpuSupport();

    expect(result.supported).toBe(false);
    expect(result.reasonCode).toBe("no-api");
  });

  test("a navigator.gpu getter that throws is contained", async () => {
    Object.defineProperty(navigator, "gpu", {
      configurable: true,
      get() {
        throw new Error("boom");
      },
    });

    const result = await detectWebGpuSupport();

    expect(result.supported).toBe(false);
    expect(result.reasonCode).toBe("no-api");
  });

  test("a negative answer is NOT cached: the next call asks again", async () => {
    gpuWith(jest.fn().mockResolvedValue(null));
    const first = await settle(detectWebGpuSupport(), WEBGPU_ADAPTER_RETRY_DELAY_MS);
    expect(first.supported).toBe(false);

    // The GPU process has come up in the meantime.
    const requestAdapter = gpuWith(jest.fn().mockResolvedValue(ADAPTER));
    const second = await detectWebGpuSupport();

    expect(second.supported).toBe(true);
    expect(requestAdapter).toHaveBeenCalledTimes(1);
  });

  test("a positive answer IS cached: a canvas full of Autark nodes probes once", async () => {
    const requestAdapter = gpuWith(jest.fn().mockResolvedValue(ADAPTER));

    await detectWebGpuSupport();
    await detectWebGpuSupport();
    await detectWebGpuSupport();

    expect(requestAdapter).toHaveBeenCalledTimes(1);
  });

  test("concurrent callers share one in-flight probe", async () => {
    const requestAdapter = gpuWith(jest.fn().mockResolvedValue(ADAPTER));

    const [a, b] = await Promise.all([detectWebGpuSupport(), detectWebGpuSupport()]);

    expect(a.supported).toBe(true);
    expect(b.supported).toBe(true);
    expect(requestAdapter).toHaveBeenCalledTimes(1);
  });

  test("reprobeWebGpuSupport forgets a positive answer and asks again", async () => {
    const requestAdapter = gpuWith(jest.fn().mockResolvedValue(ADAPTER));
    await detectWebGpuSupport();

    await reprobeWebGpuSupport();

    expect(requestAdapter).toHaveBeenCalledTimes(2);
  });

  test("__resetWebGpuSupportCache forgets a positive answer", async () => {
    const requestAdapter = gpuWith(jest.fn().mockResolvedValue(ADAPTER));
    await detectWebGpuSupport();

    __resetWebGpuSupportCache();
    await detectWebGpuSupport();

    expect(requestAdapter).toHaveBeenCalledTimes(2);
  });
});
