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

/** The router's base path, as `index.tsx` gives it to `BrowserRouter`. */
const BASENAME = (process.env.PUBLIC_PATH || "/").replace(/\/$/, "");

/**
 * The in-app path a sanitized agent link points at, or null for an external one.
 *
 * A path (`/catalog/data/x`) or an absolute URL on this origin is a Curio page,
 * and goes through the router like every other in-app link: same tab, the
 * deployment's base path applied, and the unsaved-changes question asked. It
 * used to open in a new tab as a raw href, which skipped all three.
 */
export function agentLinkAppPath(href: string): string | null {
  if (href.startsWith("/") && !href.startsWith("//")) return href;
  if (typeof window === "undefined") return null;
  let parsed: URL;
  try {
    parsed = new URL(href);
  } catch {
    return null;
  }
  if (parsed.origin !== window.location.origin) return null;
  let path = parsed.pathname;
  if (BASENAME && (path === BASENAME || path.startsWith(`${BASENAME}/`))) {
    path = path.slice(BASENAME.length) || "/";
  }
  return `${path}${parsed.search}${parsed.hash}`;
}
