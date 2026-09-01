/**
 * The agent-content URL policy (memo dev/39; REQ-SEC-002 / RISK-RENDER-001).
 *
 * Agent/model/tool content is untrusted. This module is the single place the
 * allowed link/image schemes are named: `http(s)` and `mailto` only —
 * everything else (javascript:, data:, vbscript:, file:, blob:, protocol
 * tricks with whitespace/control chars) is neutralized by returning
 * `undefined`, which makes react-markdown drop the URL entirely.
 */

const ALLOWED_SCHEMES = ["http:", "https:", "mailto:"];

/** react-markdown `urlTransform`: the sanitized URL, or undefined to drop it. */
export function sanitizeAgentUrl(url: string): string | undefined {
  if (typeof url !== "string" || !url.trim()) return undefined;
  let parsed: URL;
  try {
    // A base is required so relative URLs parse; they resolve to http(s).
    parsed = new URL(url, "https://relative.invalid/");
  } catch {
    return undefined;
  }
  return ALLOWED_SCHEMES.includes(parsed.protocol) ? url : undefined;
}
