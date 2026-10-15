/**
 * Does this browser actually have a usable WebGPU adapter? (#201, #272)
 *
 * Nothing in the app asked before: `autkGrammarBehavior` constructed and ran
 * the grammar unconditionally, and `@urban-toolkit/autk-map` swallows its own
 * init failure - `Renderer.init()` only `console.error`s "WebGPU is not
 * available" and leaves `_device` undefined, so `AutkMap.init()` carries on
 * until the layer loader reaches `this._renderer.device.createShaderModule`
 * and throws the reported TypeError.
 *
 * Presence of `navigator.gpu` is not enough on its own. Chrome exposes it on
 * hardware it then refuses to run on (blocklisted drivers, a headless run with
 * no adapter), where `requestAdapter()` resolves **null** rather than throwing,
 * so the probe has to go all the way to an adapter.
 *
 * One answer is not enough either (#272). Firefox starts its GPU process
 * lazily, and the first `requestAdapter()` after page load can resolve `null`
 * while a second call 150 ms later returns the adapter - `@urban-toolkit/
 * autk-compute`'s own device manager retries for exactly this reason. The
 * first version of this probe took the first answer and memoised it for the
 * life of the page, so a Firefox with WebGPU fully enabled was told it had
 * none, on every Autark node, until a reload. Hence: retry once, bound the
 * whole probe with a timeout so a hung GPU process cannot hold a run open,
 * and never cache a negative answer - a "no" is re-asked on the next run.
 *
 * Nor is it asked before the page has drawn (#926). Chrome can start a page on
 * GPU compositing and switch it to software compositing once its GPU process
 * is up, and the switch drops a WebGPU request in flight: requestAdapter()
 * resolves null ("A valid external Instance reference no longer exists."),
 * however long it waited for the GPU process. A request made while a slow GPU
 * process starts can wait seconds and come back null after the retry budget
 * is spent, so an Autark node that mounts with a restored input keeps its map
 * undrawn until Play. The page draws its first frame only after the switch,
 * so the probe waits for a drawn frame, up to a limit, before it asks.
 */

export type WebGpuUnsupportedReason =
  /** `navigator.gpu` is hidden because the page is not a secure context. */
  | "insecure-context"
  /** No `navigator.gpu`, or one missing the calls Autark needs. */
  | "no-api"
  /** `requestAdapter()` resolved null twice. */
  | "no-adapter"
  /** `requestAdapter()` rejected. */
  | "request-failed"
  /** Neither attempt answered within the probe timeout. */
  | "timed-out";

export interface WebGpuSupport {
  supported: boolean;
  /** Why not, phrased for a user rather than a log. Absent when supported. */
  reason?: string;
  /** Why not, for code and tests. Absent when supported. */
  reasonCode?: WebGpuUnsupportedReason;
  /** The frame wait, timed from the start of the probe: "drew a frame at
   *  33 ms", or "drew no frame in 10000 ms". Absent when the page had drawn
   *  already. For logs and the e2e tests, like `answers`. */
  frame?: string;
  /** Every adapter request's answer, timed from the start of the probe:
   *  "null at 33 ms", "an adapter at 183 ms". */
  answers?: string[];
}

/** How long the second `requestAdapter()` waits for the GPU process (#272).
 *  The value autk-compute uses; a cold Firefox GPU process is well inside it. */
export const WEBGPU_ADAPTER_RETRY_DELAY_MS = 150;

/** Ceiling for the backoff between adapter requests. */
export const WEBGPU_ADAPTER_RETRY_MAX_DELAY_MS = 1_000;

/**
 * How long the probe keeps asking for an adapter before calling it missing
 * (#272).
 *
 * Distinct from WEBGPU_PROBE_TIMEOUT_MS, which bounds a requestAdapter() that
 * never settles at all. This one bounds a browser answering "null" promptly and
 * repeatedly - a GPU process that is still coming up - and it is a UX trade, not
 * a safety margin: every second here is a second a browser that genuinely has no
 * adapter waits before its fallback panel appears, on every run. Three seconds
 * covers the "a second or more" cold start the report describes; anything slower
 * is what the panel's "Check again" is for. It counts from the first request,
 * after the frame wait.
 */
export const WEBGPU_ADAPTER_RETRY_BUDGET_MS = 3_000;

/**
 * How long the probe waits for the page to draw a frame before its first
 * adapter request, when no frame comes (#926).
 *
 * The switch to software compositing waits for the GPU process, which took up
 * to 9 s to start on a GPU that several test jobs shared, and the page draws
 * its first frame only after the switch. A visible page that draws nothing for
 * this long has nothing on screen to hold up. A hidden tab draws no frames, so
 * its first probe waits all of this before it asks; showing the tab draws a
 * frame and ends the wait.
 */
export const WEBGPU_FRAME_WAIT_MS = 10_000;

/** Overridable so suites about the fallback UI need not spend the budget. */
let adapterRetryBudgetMs = WEBGPU_ADAPTER_RETRY_BUDGET_MS;

/** Upper bound on the adapter requests, counted from the first one (the frame
 *  wait comes before it). A healthy adapter answers in milliseconds
 *  and a software adapter in CI within two or three seconds, so anything past
 *  this is a GPU process that is not coming back; far below the ten-minute
 *  run watchdog, which used to be the only thing that ended a hung probe. */
export const WEBGPU_PROBE_TIMEOUT_MS = 8_000;

/** Memoised across calls while an answer is pending or positive: a canvas full
 *  of Autark nodes probes once, not once per node. A negative answer clears the
 *  memo (see `detectWebGpuSupport`), so the next run asks again. */
let cached: Promise<WebGpuSupport> | null = null;

/** Set once the page has drawn a frame. The switch the frame wait is for comes
 *  before the first frame, so from then on the probe asks at once. */
let frameDrawn = false;

const CHECK_AGAIN = " Press Check again on the node to re-test.";

const COPY: Record<WebGpuUnsupportedReason, string> = {
  "insecure-context":
    "WebGPU is only available on secure pages (https://, or http://localhost). " +
    "This page is served over plain http://, so the browser hides it. Open Curio " +
    "through https or localhost.",
  "no-api":
    "This browser does not expose WebGPU. Use Chrome or Edge; in Firefox, set " +
    "dom.webgpu.enabled to true in about:config and reload the page.",
  "no-adapter":
    "WebGPU is present but the browser returned no graphics adapter, after " +
    "retrying while the GPU process might still have been starting. This is " +
    "usually a blocklisted driver or a headless session." + CHECK_AGAIN,
  "request-failed":
    "WebGPU is present but requesting a graphics adapter failed." + CHECK_AGAIN,
  "timed-out":
    `WebGPU did not answer within ${WEBGPU_PROBE_TIMEOUT_MS / 1000} seconds. The GPU ` +
    "process may still be starting." + CHECK_AGAIN,
};

interface GpuLike {
  requestAdapter?: () => Promise<unknown>;
  getPreferredCanvasFormat?: () => unknown;
}

function unsupported(reasonCode: WebGpuUnsupportedReason, detail?: string): WebGpuSupport {
  const reason = detail ? `${COPY[reasonCode]} (${detail})` : COPY[reasonCode];
  return { supported: false, reason, reasonCode };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Resolve once the page has drawn a frame, or after WEBGPU_FRAME_WAIT_MS, with
 * the probe's note on it. A frame is drawn once the next one starts: the first
 * animation frame callback runs while its frame is still being made, and the
 * switch to software compositing can land just after it.
 */
function waitForADrawnFrame(started: number): Promise<string> {
  return new Promise((resolve) => {
    const timer = setTimeout(
      () => resolve(`drew no frame in ${WEBGPU_FRAME_WAIT_MS} ms`),
      WEBGPU_FRAME_WAIT_MS,
    );
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        frameDrawn = true;
        clearTimeout(timer);
        resolve(`drew a frame at ${Date.now() - started} ms`);
      });
    });
  });
}

async function requestAdapterUntil(
  gpu: GpuLike,
  deadline: number,
  note: (answer: string) => void,
): Promise<WebGpuSupport> {
  // Keep asking until the probe's own budget runs out, rather than once more
  // after 150 ms (#272). The premise of the retry is a GPU process that starts
  // lazily, and on a cold session it can take a second or more to come up -
  // Firefox on Linux with a discrete card is the reported case. A single early
  // retry answers "no adapter" for exactly the browsers the retry exists for,
  // while WEBGPU_PROBE_TIMEOUT_MS sits unused because requestAdapter() did
  // answer - with null, promptly, every time.
  //
  // Backs off so a slow start is not billed dozens of adapter requests: 150 ms,
  // then doubling to a 1 s ceiling.
  let wait = WEBGPU_ADAPTER_RETRY_DELAY_MS;
  for (;;) {
    try {
      const adapter = await gpu.requestAdapter!();
      note(adapter ? "an adapter" : "null");
      if (adapter) return { supported: true };
    } catch (err) {
      // A rejection is a different answer from "not yet": the call failed
      // rather than reporting no adapter, and retrying it says the same thing
      // more slowly.
      const message = (err as Error)?.message || "requestAdapter rejected";
      note(`rejected (${message})`);
      return unsupported("request-failed", message);
    }
    if (Date.now() + wait >= deadline) return unsupported("no-adapter");
    await sleep(wait);
    wait = Math.min(wait * 2, WEBGPU_ADAPTER_RETRY_MAX_DELAY_MS);
  }
}

async function probe(): Promise<WebGpuSupport> {
  let gpu: GpuLike | undefined;
  try {
    gpu = (navigator as unknown as { gpu?: GpuLike }).gpu;
  } catch (err) {
    // A getter that throws is a broken implementation, not a missing one.
    return unsupported("no-api", (err as Error)?.message || "navigator.gpu threw");
  }
  if (!gpu) {
    const insecure =
      typeof window !== "undefined" && (window as { isSecureContext?: boolean }).isSecureContext === false;
    return unsupported(insecure ? "insecure-context" : "no-api");
  }
  // autk-map calls getPreferredCanvasFormat() synchronously before it ever
  // requests an adapter, so an implementation without it fails inside the
  // library with a TypeError that says nothing about WebGPU.
  if (typeof gpu.requestAdapter !== "function" || typeof gpu.getPreferredCanvasFormat !== "function") {
    return unsupported("no-api", "incomplete WebGPU implementation");
  }

  const started = Date.now();
  const answers: string[] = [];
  const note = (answer: string) => {
    answers.push(`${answer} at ${Date.now() - started} ms`);
  };
  // Once a frame has been drawn there is nothing to wait for, not even a
  // promise tick. Without animation frames (no window) there is no frame to
  // wait for either.
  const canWait = typeof window !== "undefined" && typeof window.requestAnimationFrame === "function";
  const frame = frameDrawn || !canWait ? undefined : await waitForADrawnFrame(started);

  // The retry budget and the timeout count from the first request.
  let timer: ReturnType<typeof setTimeout> | null = null;
  const timeout = new Promise<WebGpuSupport>((resolve) => {
    timer = setTimeout(() => {
      answers.push(`no answer in ${WEBGPU_PROBE_TIMEOUT_MS} ms`);
      resolve(unsupported("timed-out"));
    }, WEBGPU_PROBE_TIMEOUT_MS);
  });
  try {
    const result = await Promise.race([
      requestAdapterUntil(gpu, Date.now() + adapterRetryBudgetMs, note),
      timeout,
    ]);
    return { ...result, ...(frame ? { frame } : {}), answers: [...answers] };
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export function detectWebGpuSupport(): Promise<WebGpuSupport> {
  if (!cached) {
    const pending = probe().then((result) => {
      // Only a "yes" is worth remembering. A "no" may be the GPU process
      // starting up, a pref the user is about to flip, or a transient
      // failure - re-asking costs one call, being wrong costs every Autark
      // node in the tab (#272).
      if (!result.supported && cached === pending) cached = null;
      return result;
    });
    cached = pending;
  }
  return cached;
}

/** Forget any answer and ask again - what the node's "Check again" button does. */
export function reprobeWebGpuSupport(): Promise<WebGpuSupport> {
  cached = null;
  return detectWebGpuSupport();
}

/**
 * One probe, outside the memo: it neither reads nor keeps the app's answer.
 * The e2e tests ask through it (backend/tests/test_frontend/utils/webgpu.py,
 * as `window.__curio_probeWebGpu`), so they wait and retry exactly as the app
 * does, and read the probe's record.
 */
export function runWebGpuProbe(): Promise<WebGpuSupport> {
  return probe();
}

if (typeof window !== "undefined") {
  (window as unknown as { __curio_probeWebGpu?: () => Promise<WebGpuSupport> }).__curio_probeWebGpu =
    runWebGpuProbe;
}

/** Test-only: drops the memoised answer, and the page's drawn frame, so a case
 *  can install its own `navigator.gpu` and be probed afresh, as on a page just
 *  opened. */
export function __resetWebGpuSupportCache(): void {
  cached = null;
  frameDrawn = false;
}

/** Test-only: shorten (or restore) the adapter retry budget. A suite whose
 *  subject is the fallback UI rather than the retry policy sets this to 0 so it
 *  is not billed the real wait for every "no adapter" case. */
export function __setWebGpuAdapterRetryBudget(ms: number): void {
  adapterRetryBudgetMs = ms;
}
