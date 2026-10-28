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
 * software compositing drops a request made before it. When that wait runs
 * out and every request went before the page drew, a "no" waits for a frame
 * once more and is asked again if one comes.
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
    const requestAdapter = gpuWith(jest.fn(() => new Promise(() => undefined)));

    const pending = detectWebGpuSupport();
    let answered = false;
    void pending.then(() => { answered = true; });
    // Given up 8 s after it was made, the probe waits for a frame once more
    // (#1017), and a page that still draws nothing keeps that answer.
    await jest.advanceTimersByTimeAsync(2 * WEBGPU_FRAME_WAIT_MS + WEBGPU_PROBE_TIMEOUT_MS - 1);
    expect(answered).toBe(false);

    await jest.advanceTimersByTimeAsync(1);
    expect(answered).toBe(true);
    const result = await pending;
    expect(result.reasonCode).toBe("timed-out");
    expect(result.answers).toEqual([`no answer in ${WEBGPU_PROBE_TIMEOUT_MS} ms`]);
    expect(requestAdapter).toHaveBeenCalledTimes(1);
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
    await jest.advanceTimersByTimeAsync(2 * WEBGPU_FRAME_WAIT_MS + WEBGPU_PROBE_TIMEOUT_MS);

    expect(await pending).toMatchObject({
      supported: false,
      reasonCode: "timed-out",
      frame: `drew no frame in ${WEBGPU_FRAME_WAIT_MS} ms, nor by ${2 * WEBGPU_FRAME_WAIT_MS + WEBGPU_PROBE_TIMEOUT_MS} ms`,
      answers: [`no answer in ${WEBGPU_PROBE_TIMEOUT_MS} ms`],
    });
  });
});

/**
 * A freshly launched Chrome on a GPU that several test jobs share can draw
 * nothing for longer than the probe's wait (#1017). The probe then asks while
 * the GPU process is still starting, and the switch to software compositing
 * answers that request null after the 3 s of retries, or past the 8 s the
 * probe gives it. The page draws right after the switch. A dashboard runs its
 * GPU steps on the probe's answer as it opens, so that answer left all of them
 * unrun (run 40777113421). A probe whose wait ran out and that found no
 * adapter waits for a frame once more, and asks again if one comes.
 */
describe("a probe that asked while the page drew nothing asks again once it draws", () => {
  /** When the switch answered the dropped request in run 40777113421: 3562 ms
   *  after it, past the 3 s of retries. */
  const SWITCH_AFTER_MS = 3_562;

  beforeEach(() => {
    pageFrames.held = true;
  });

  /**
   * A requestAdapter whose first request waits for the switch, which answers
   * it null when `dropped` is called; every later request answers *later*,
   * and each request's time is kept.
   */
  function droppedThen(later: unknown) {
    const askedAt: number[] = [];
    let answerTheSwitch: (value: null) => void = () => undefined;
    const requestAdapter = gpuWith(jest.fn(() => {
      askedAt.push(Date.now());
      if (askedAt.length === 1) return new Promise((resolve) => { answerTheSwitch = resolve; });
      return Promise.resolve(later);
    }));
    return { requestAdapter, askedAt, dropped: () => answerTheSwitch(null) };
  }

  /** The page draws: the frame the wait asked for, then the next one. */
  async function draws() {
    drawFrame();
    await flush();
    drawFrame();
    await flush();
  }

  test("a request the switch answers null after the retries is asked again once the page draws", async () => {
    const { requestAdapter, askedAt, dropped } = droppedThen(ADAPTER);

    const pending = detectWebGpuSupport();
    await jest.advanceTimersByTimeAsync(WEBGPU_FRAME_WAIT_MS + SWITCH_AFTER_MS);
    dropped();
    await jest.advanceTimersByTimeAsync(0);
    // The retry budget is spent, and nothing is asked while the page draws nothing.
    expect(requestAdapter).toHaveBeenCalledTimes(1);
    await jest.advanceTimersByTimeAsync(1_000);
    expect(requestAdapter).toHaveBeenCalledTimes(1);

    await draws();

    const at = WEBGPU_FRAME_WAIT_MS + SWITCH_AFTER_MS + 1_000;
    expect(await pending).toEqual({
      supported: true,
      frame: `drew no frame in ${WEBGPU_FRAME_WAIT_MS} ms, then a frame at ${at} ms`,
      answers: [`null at ${WEBGPU_FRAME_WAIT_MS + SWITCH_AFTER_MS} ms`, `an adapter at ${at} ms`],
    });
    expect(askedAt.map((time) => time - askedAt[0])).toEqual([0, SWITCH_AFTER_MS + 1_000]);
  });

  test("a request the switch answers only after the probe gave up on it is asked again once the page draws", async () => {
    const { requestAdapter, dropped } = droppedThen(ADAPTER);

    const pending = detectWebGpuSupport();
    await jest.advanceTimersByTimeAsync(WEBGPU_FRAME_WAIT_MS + WEBGPU_PROBE_TIMEOUT_MS);
    expect(requestAdapter).toHaveBeenCalledTimes(1);
    // The switch, 9 s after the request, as in main's run 39072275174.
    await jest.advanceTimersByTimeAsync(1_000);
    dropped();
    await draws();

    const at = WEBGPU_FRAME_WAIT_MS + WEBGPU_PROBE_TIMEOUT_MS + 1_000;
    expect(await pending).toEqual({
      supported: true,
      frame: `drew no frame in ${WEBGPU_FRAME_WAIT_MS} ms, then a frame at ${at} ms`,
      answers: [`no answer in ${WEBGPU_PROBE_TIMEOUT_MS} ms`, `null at ${at} ms`, `an adapter at ${at} ms`],
    });
    expect(requestAdapter).toHaveBeenCalledTimes(2);
  });

  test("a browser with no adapter still has none once its page draws, after one more round of the retry rule", async () => {
    const { askedAt, dropped } = droppedThen(null);

    const pending = detectWebGpuSupport();
    await jest.advanceTimersByTimeAsync(WEBGPU_FRAME_WAIT_MS + SWITCH_AFTER_MS);
    dropped();
    await jest.advanceTimersByTimeAsync(0);
    await draws();
    await jest.advanceTimersByTimeAsync(30_000);
    const result = await pending;

    expect(result).toMatchObject({
      supported: false,
      reasonCode: "no-adapter",
      frame: `drew no frame in ${WEBGPU_FRAME_WAIT_MS} ms, then a frame at ${WEBGPU_FRAME_WAIT_MS + SWITCH_AFTER_MS} ms`,
    });
    // The dropped request, then 150 ms, doubling to 1 s, for 3 s from the
    // first request made once the page drew.
    expect(askedAt.map((time) => time - askedAt[1])).toEqual([-SWITCH_AFTER_MS, 0, 150, 450, 1050, 2050]);
  });

  test("a page that draws before the answer is not waited for again", async () => {
    const { requestAdapter, askedAt, dropped } = droppedThen(null);

    const pending = detectWebGpuSupport();
    await jest.advanceTimersByTimeAsync(WEBGPU_FRAME_WAIT_MS);
    // The page draws while the request waits for the switch, which answers it
    // null within the retries: the next request goes 150 ms later, as ever.
    await draws();
    await jest.advanceTimersByTimeAsync(500);
    dropped();
    await jest.advanceTimersByTimeAsync(30_000);
    const result = await pending;

    expect(result.reasonCode).toBe("no-adapter");
    expect(result.frame).toBe(`drew no frame in ${WEBGPU_FRAME_WAIT_MS} ms`);
    expect(askedAt.map((time) => time - askedAt[0])).toEqual([0, 650, 950, 1550, 2550]);
    expect(requestAdapter).toHaveBeenCalledTimes(5);
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
