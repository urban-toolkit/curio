/**
 * Node-content extraction (memo dev/57) — the frontend mirror of the backend
 * `content.extract_node_content`, used by the legacy Get Code path (which
 * previously did a crude `replaceAll("```python", …)` that missed language
 * ids, kept explanatory prose, and corrupted legitimate backticks).
 *
 * Deterministic and conservative: JSON wrappers carrying a single plausible
 * string field unwrap; when fenced blocks exist the LARGEST block's body is
 * the content (language identifier dropped, surrounding prose discarded);
 * unfenced text returns trimmed and otherwise untouched — the legacy
 * "not controllable" sentinel passes through exactly.
 */

const FENCE_RE = /```[A-Za-z0-9.\-]*\n([\s\S]*?)\n```/g;
const WRAPPER_KEYS = ["content", "code", "source", "result"] as const;

export function extractNodeContent(text: unknown): string {
  if (typeof text !== "string") return "";
  let current = text.trim();
  for (let i = 0; i < 3; i++) {
    // 1. Whole-text JSON wrapper with one plausible content field.
    if (current.startsWith("{") && current.endsWith("}")) {
      let payload: unknown = null;
      try {
        payload = JSON.parse(current);
      } catch {
        payload = null;
      }
      if (payload && typeof payload === "object" && !Array.isArray(payload)) {
        const record = payload as Record<string, unknown>;
        const stringFields = WRAPPER_KEYS.filter((k) => typeof record[k] === "string");
        if (stringFields.length === 1) {
          current = (record[stringFields[0]] as string).trim();
          continue;
        }
      }
    }
    // 2. Fenced blocks: the largest body is the content.
    const fences = [...current.matchAll(FENCE_RE)];
    if (fences.length) {
      const largest = fences.reduce((a, b) => (b[1].length > a[1].length ? b : a));
      current = largest[1].trim();
      continue;
    }
    break;
  }
  return current;
}
