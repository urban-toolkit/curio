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
}

/** How long the second `requestAdapter()` waits for the GPU process (#272).
 *  The value autk-compute uses; a cold Firefox GPU process is well inside it. */
export const WEBGPU_ADAPTER_RETRY_DELAY_MS = 150;

/** Upper bound on the whole probe. A healthy adapter answers in milliseconds
 *  and a software adapter in CI within two or three seconds, so anything past
 *  this is a GPU process that is not coming back; far below the ten-minute
 *  run watchdog, which used to be the only thing that ended a hung probe. */
export const WEBGPU_PROBE_TIMEOUT_MS = 8_000;

/** Memoised across calls while an answer is pending or positive: a canvas full
 *  of Autark nodes probes once, not once per node. A negative answer clears the
 *  memo (see `detectWebGpuSupport`), so the next run asks again. */
let cached: Promise<WebGpuSupport> | null = null;

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
    "WebGPU is present but the browser returned no graphics adapter, even after a " +
    "retry. This is usually a blocklisted driver, a headless session, or a GPU " +
    "process that is still starting." + CHECK_AGAIN,
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

async function requestAdapterWithRetry(gpu: GpuLike): Promise<WebGpuSupport> {
  try {
    let adapter = await gpu.requestAdapter!();
    if (!adapter) {
      // Firefox: the GPU process is still coming up. Ask once more.
      await sleep(WEBGPU_ADAPTER_RETRY_DELAY_MS);
      adapter = await gpu.requestAdapter!();
    }
    if (!adapter) return unsupported("no-adapter");
    return { supported: true };
  } catch (err) {
    return unsupported(
      "request-failed",
      (err as Error)?.message || "requestAdapter rejected",
    );
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

  let timer: ReturnType<typeof setTimeout> | null = null;
  const timeout = new Promise<WebGpuSupport>((resolve) => {
    timer = setTimeout(() => resolve(unsupported("timed-out")), WEBGPU_PROBE_TIMEOUT_MS);
  });
  try {
    return await Promise.race([requestAdapterWithRetry(gpu), timeout]);
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

/** Test-only: drops the memoised answer so a case can install its own
 *  `navigator.gpu` and be probed afresh. */
export function __resetWebGpuSupportCache(): void {
  cached = null;
}
