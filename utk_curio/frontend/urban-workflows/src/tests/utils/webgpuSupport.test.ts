/**
 * The WebGPU probe answers the question Firefox actually poses (#272).
 *
 * Firefox with `dom.webgpu.enabled` on, verified working by third-party
 * checkers, was still told by Curio that it had no WebGPU. The probe asked
 * `requestAdapter()` once, took the `null` Firefox returns while its GPU
 * process is still starting, and memoised that answer for the life of the
 * page. Every case here is one of the ways that single-shot, cache-forever
 * probe was wrong.
 *
 * The cases at the end are about what comes before the first request: the
 * probe waits until the page has drawn a frame, because Chrome's switch to
 * software compositing drops a request made before it.
 */
import fs from "fs";
import path from "path";
import {
  detectWebGpuSupport,
  reprobeWebGpuSupport,
  WEBGPU_ADAPTER_RETRY_DELAY_MS,
  WEBGPU_FRAME_WAIT_MS,
  WEBGPU_PROBE_TIMEOUT_MS,
  __resetWebGpuSupportCache,
} from "../../utils/webgpuSupport";

const ADAPTER = { name: "fake-adapter" };

/**
 * The page's animation frames. Each runs at once by default: a page that
 * draws, as every page has by the time a user runs an Autark node. A case
 * about the frame wait holds them instead, and draws them one at a time with
 * drawFrame(), or never (a hidden tab draws none).
 */
const pageFrames = { held: false, waiting: [] as FrameRequestCallback[] };
const realRequestAnimationFrame = window.requestAnimationFrame;

function drawFrame() {
  const due = pageFrames.waiting;
  pageFrames.waiting = [];
  due.forEach((callback) => callback(Date.now()));
}

/** Let every promise callback that is due run. */
async function flush() {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

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
  // Let the page's frame pass, the first requestAdapter() resolve and the
  // retry timer be armed.
  await flush();
  jest.advanceTimersByTime(advanceMs);
  return promise;
}

/**
 * Drive the retry loop to its end under fake timers.
 *
 * The probe keeps asking until its budget runs out (#272), so a single advance
 * is not enough: each attempt arms the next timer only after its own
 * requestAdapter() has resolved. Pump microtasks and the clock together until
 * the probe answers.
 */
async function drain<T>(promise: Promise<T>, stepMs = 250, steps = 80): Promise<T> {
  let pending = true;
  const settled = promise.then((value) => { pending = false; return value; });
  for (let i = 0; i < steps && pending; i += 1) {
    await Promise.resolve();
    await Promise.resolve();
    jest.advanceTimersByTime(stepMs);
  }
  return settled;
}

beforeEach(() => {
  // Animation frames are the page's (above), not 16 ms timers.
  jest.useFakeTimers({ doNotFake: ["requestAnimationFrame", "cancelAnimationFrame"] });
  pageFrames.held = false;
  pageFrames.waiting = [];
  window.requestAnimationFrame = (callback: FrameRequestCallback) => {
    if (pageFrames.held) pageFrames.waiting.push(callback);
    else callback(Date.now());
    return 0;
  };
  __resetWebGpuSupportCache();
  setSecureContext(true);
  installGpu(undefined);
});

afterEach(() => {
  jest.useRealTimers();
  window.requestAnimationFrame = realRequestAnimationFrame;
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

  test("null for the whole budget is a missing adapter, and says to check again", async () => {
    const requestAdapter = gpuWith(jest.fn().mockResolvedValue(null));

    const result = await drain(detectWebGpuSupport());

    expect(result.supported).toBe(false);
    expect(result.reasonCode).toBe("no-adapter");
    expect(result.reason).toMatch(/Check again/);
    // It asked more than the one early retry that used to be the whole policy.
    expect(requestAdapter.mock.calls.length).toBeGreaterThan(2);
  });

  test("an adapter that only appears after several retries is still found", async () => {
    // The #272 residue: the GPU process starts lazily, and on a cold session it
    // can take a second or more. Two calls 150 ms apart answered "no adapter"
    // for precisely the browsers the retry exists for.
    const requestAdapter = gpuWith(
      jest.fn()
        .mockResolvedValueOnce(null)
        .mockResolvedValueOnce(null)
        .mockResolvedValueOnce(null)
        .mockResolvedValueOnce(null)
        .mockResolvedValue(ADAPTER),
    );

    const result = await drain(detectWebGpuSupport());

    expect(result.supported).toBe(true);
    expect(requestAdapter.mock.calls.length).toBeGreaterThan(2);
  });

  test("the probe stops asking once its budget is spent", async () => {
    // The loop has to end on its own: the outer timeout only fires when
    // requestAdapter never settles, and this one answers null promptly for ever.
    const requestAdapter = gpuWith(jest.fn().mockResolvedValue(null));

    const result = await drain(detectWebGpuSupport());
    const askedByTheEnd = requestAdapter.mock.calls.length;

    expect(result.reasonCode).toBe("no-adapter");
    jest.advanceTimersByTime(WEBGPU_PROBE_TIMEOUT_MS * 2);
    await Promise.resolve();
    expect(requestAdapter.mock.calls.length).toBe(askedByTheEnd);
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
    await flush();
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
    const first = await drain(detectWebGpuSupport());
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

/**
 * Chrome can start a page on GPU compositing and switch it to software
 * compositing once its GPU process is up. The switch drops a WebGPU request in
 * flight: requestAdapter() resolves null ("A valid external Instance reference
 * no longer exists."), however long it has waited for the GPU process. The
 * page draws its first frame only after the switch, so the probe asks once a
 * frame is drawn. A request made earlier can wait seconds for a slow GPU
 * process and then come back null, too late for the retry (#926).
 */
describe("before its first request, the probe waits until the page has drawn a frame", () => {
  beforeEach(() => {
    pageFrames.held = true;
  });

  test("nothing is asked while the page has drawn nothing; the first request follows the first drawn frame", async () => {
    const requestAdapter = gpuWith(jest.fn().mockResolvedValue(ADAPTER));

    const pending = detectWebGpuSupport();
    await flush();
    expect(requestAdapter).not.toHaveBeenCalled();

    // The first animation frame runs while that frame is still being made,
    // and the switch can land right after it.
    drawFrame();
    await flush();
    expect(requestAdapter).not.toHaveBeenCalled();

    // The next one starts once the first frame is drawn.
    drawFrame();
    await flush();
    expect(requestAdapter).toHaveBeenCalledTimes(1);
    expect((await pending).supported).toBe(true);
  });

  test("a page that draws no frame, such as a hidden tab, is asked anyway when the wait ends", async () => {
    const requestAdapter = gpuWith(jest.fn().mockResolvedValue(ADAPTER));

    const pending = detectWebGpuSupport();
    await flush();
    jest.advanceTimersByTime(WEBGPU_FRAME_WAIT_MS - 1);
    await flush();
    expect(requestAdapter).not.toHaveBeenCalled();

    jest.advanceTimersByTime(1);
    await flush();
    expect(requestAdapter).toHaveBeenCalledTimes(1);
    expect((await pending).supported).toBe(true);
  });

  test("after the wait, the retry rule is the one it was: 150 ms, doubling to 1 s, for 3 s from the first request", async () => {
    const askedAt: number[] = [];
    gpuWith(jest.fn(() => {
      askedAt.push(Date.now());
      return Promise.resolve(null);
    }));

    const pending = detectWebGpuSupport();
    // No frame comes, so the whole wait passes before the first request: if
    // the retry budget counted from the start of the wait, it would be spent.
    await jest.advanceTimersByTimeAsync(30_000);
    const result = await pending;

    expect(result.reasonCode).toBe("no-adapter");
    expect(askedAt.map((at) => at - askedAt[0])).toEqual([0, 150, 450, 1050, 2050]);
  });

  test("a request that never answers is given up 8 s after it was made, not 8 s after the wait began", async () => {
    gpuWith(jest.fn(() => new Promise(() => undefined)));

    const pending = detectWebGpuSupport();
    let answered = false;
    void pending.then(() => { answered = true; });
    await jest.advanceTimersByTimeAsync(WEBGPU_FRAME_WAIT_MS + WEBGPU_PROBE_TIMEOUT_MS - 1);
    expect(answered).toBe(false);

    await jest.advanceTimersByTimeAsync(1);
    expect(answered).toBe(true);
    expect((await pending).reasonCode).toBe("timed-out");
  });

  test("once the page has drawn a frame, later probes ask at once", async () => {
    gpuWith(jest.fn().mockResolvedValue(ADAPTER));
    const first = detectWebGpuSupport();
    await flush();
    drawFrame();
    await flush();
    drawFrame();
    expect((await first).supported).toBe(true);

    // "Check again" on the node.
    const requestAdapter = gpuWith(jest.fn().mockResolvedValue(ADAPTER));
    const again = reprobeWebGpuSupport();
    await flush();

    expect(requestAdapter).toHaveBeenCalledTimes(1);
    expect(pageFrames.waiting).toHaveLength(0);
    expect((await again).supported).toBe(true);
  });

  test("the probe says when the page drew and what each request answered, and when", async () => {
    gpuWith(jest.fn().mockResolvedValueOnce(null).mockResolvedValue(ADAPTER));

    const pending = detectWebGpuSupport();
    await jest.advanceTimersByTimeAsync(100);
    drawFrame();
    drawFrame();
    await flush();
    await jest.advanceTimersByTimeAsync(WEBGPU_ADAPTER_RETRY_DELAY_MS);

    expect(await pending).toEqual({
      supported: true,
      frame: "drew a frame at 100 ms",
      answers: ["null at 100 ms", "an adapter at 250 ms"],
    });
  });

  test("the record of a page that drew no frame and a browser that never answered", async () => {
    gpuWith(jest.fn(() => new Promise(() => undefined)));

    const pending = detectWebGpuSupport();
    await jest.advanceTimersByTimeAsync(WEBGPU_FRAME_WAIT_MS + WEBGPU_PROBE_TIMEOUT_MS);

    expect(await pending).toMatchObject({
      supported: false,
      reasonCode: "timed-out",
      frame: `drew no frame in ${WEBGPU_FRAME_WAIT_MS} ms`,
      answers: [`no answer in ${WEBGPU_PROBE_TIMEOUT_MS} ms`],
    });
  });
});

/**
 * The e2e tests ask for an adapter through the app's probe itself
 * (backend/tests/test_frontend/utils/webgpu.py), so the wait and the retry
 * live in one place.
 */
describe("the e2e tests ask through the app's own probe", () => {
  const hook = () => (window as unknown as { __curio_probeWebGpu?: () => Promise<unknown> }).__curio_probeWebGpu;

  test("window.__curio_probeWebGpu runs a fresh probe, outside the app's memo", async () => {
    const requestAdapter = gpuWith(jest.fn().mockResolvedValue(ADAPTER));
    expect(typeof hook()).toBe("function");

    await detectWebGpuSupport();
    expect(await hook()!()).toMatchObject({ supported: true, answers: ["an adapter at 0 ms"] });
    // Asked again rather than handed the app's answer...
    expect(requestAdapter).toHaveBeenCalledTimes(2);

    // ...and the app's own answer is left as it was.
    await detectWebGpuSupport();
    expect(requestAdapter).toHaveBeenCalledTimes(2);
  });

  test("the helper asks only through that hook, with no adapter request of its own", () => {
    const helper = fs.readFileSync(
      path.resolve(__dirname, "../../../../../backend/tests/test_frontend/utils/webgpu.py"),
      "utf8",
    );

    expect(helper).toMatch(/window\.__curio_probeWebGpu\(\)/);
    expect(helper).not.toMatch(/\.requestAdapter\(/);
  });
});
