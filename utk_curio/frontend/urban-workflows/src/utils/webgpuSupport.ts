/**
 * Does this browser actually have a usable WebGPU device? (#201)
 *
 * Nothing in the app asked before: `autkGrammarBehavior` constructed and ran
 * the grammar unconditionally, and `@urban-toolkit/autk-map` swallows its own
 * init failure - `Renderer.init()` only `console.error`s "WebGPU is not
 * available" and leaves `_device` undefined, so `AutkMap.init()` carries on
 * until the layer loader reaches `this._renderer.device.createShaderModule`
 * and throws the reported TypeError. In Firefox and Safari that is every
 * Autark node.
 *
 * Presence of `navigator.gpu` is not enough on its own. Chrome exposes it on
 * hardware it then refuses to run on (blocklisted drivers, a headless run with
 * no adapter), where `requestAdapter()` resolves **null** rather than throwing,
 * so the probe has to go all the way to an adapter.
 */

export interface WebGpuSupport {
  supported: boolean;
  /** Why not, phrased for a user rather than a log. Absent when supported. */
  reason?: string;
}

/** Memoised across calls: `requestAdapter()` is genuinely expensive, the answer
 *  cannot change for the life of the page, and a canvas full of Autark nodes
 *  would otherwise probe once per node. */
let cached: Promise<WebGpuSupport> | null = null;

const NO_API =
  "This browser has no WebGPU support. Use Chrome or Edge, or in Firefox enable " +
  "dom.webgpu.enabled in about:config.";

const NO_ADAPTER =
  "WebGPU is present but no graphics adapter is available, so Autark cannot " +
  "render here. This is usually a blocklisted driver or a headless session; " +
  "try Chrome or Edge on a machine with a GPU.";

async function probe(): Promise<WebGpuSupport> {
  const gpu = (navigator as unknown as { gpu?: { requestAdapter(): Promise<unknown> } })
    .gpu;
  if (!gpu || typeof gpu.requestAdapter !== "function") {
    return { supported: false, reason: NO_API };
  }
  try {
    const adapter = await gpu.requestAdapter();
    if (!adapter) return { supported: false, reason: NO_ADAPTER };
    return { supported: true };
  } catch (err) {
    // Firefox throws here rather than resolving null when the pref is off.
    return {
      supported: false,
      reason: `${NO_API} (${(err as Error)?.message ?? "requestAdapter failed"})`,
    };
  }
}

export function detectWebGpuSupport(): Promise<WebGpuSupport> {
  if (!cached) cached = probe();
  return cached;
}

/** Test-only: drops the memoised answer so a case can install its own
 *  `navigator.gpu` and be probed afresh. */
export function __resetWebGpuSupportCache(): void {
  cached = null;
}
