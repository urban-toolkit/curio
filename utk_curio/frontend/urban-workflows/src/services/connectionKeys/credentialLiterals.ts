/**
 * dev/117: credential-shaped literals in node code — the editor's hint.
 *
 * The TypeScript twin of the backend's regex form (`_CRED_LITERAL_FALLBACK_RE`
 * + `_CRED_VALUE_RE` in `utk_curio/backend/app/agents/source_grounding.py`).
 * KEEP IN SYNC: both sides assert the same fixture list
 * (`credentialLiterals.test.ts` ↔ `test_source_grounding.py::TestConnectionKeys`).
 *
 * A finding is a NAME and a LINE. The matched value is dropped here and never
 * returned, stored or rendered — the hint says "line 4 looks like an API key",
 * nothing more. Pure and bounded: at most MAX_FINDINGS, code beyond MAX_SCAN_CHARS
 * is not scanned.
 */

export interface CredentialFinding {
  /** The assignment target / dict key / keyword argument that named the value. */
  name: string;
  /** 1-based line. */
  line: number;
}

export type CredentialLanguage = "python" | "javascript";

export const MAX_FINDINGS = 5;
export const MAX_SCAN_CHARS = 200_000;
/** The backend's `_CRED_VALUE_RE` bound. */
export const MIN_VALUE_CHARS = 20;

const NAME =
  "api[_-]?key|apikey|key|token|access[_-]?token|secret|api[_-]?secret|password|passwd|" +
  "auth(?:orization)?|bearer|client[_-]?secret|x[_-]api[_-]key";
const VALUE = `(?:Bearer\\s+)?[A-Za-z0-9_\\-.~+/=]{${MIN_VALUE_CHARS},}`;

// `name = "value"`, `"name": "value"`, `name="value"` (a keyword argument),
// and — JavaScript — `const name = "value"` / `{ name: "value" }`. The name
// must start a token (so `monkey = "…"` is not `key = "…"`), and the closing
// quote must match the opening one.
const LITERAL_RE = new RegExp(
  `(?:^|[\\s,{(\\[])(?:(?:const|let|var)\\s+)?["']?(${NAME})["']?\\s*[:=]\\s*(["'])(${VALUE})\\2`,
  "gi",
);

const DATA_EXTENSIONS = /\.(csv|tsv|json|geojson|parquet|shp|gpkg|tif|tiff|txt|xlsx|xls|zip|pbf|nc|h5)$/i;

/** The backend's `classify_literal` twin, reduced to what a VALUE can be:
 * a URL or a path is a source, never a credential. */
function looksLikeSource(value: string): boolean {
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) return true;
  if (/^(?:\/|\.{1,2}\/|~\/|[A-Za-z]:\\)/.test(value)) return true;
  if (value.includes("/") && DATA_EXTENSIONS.test(value)) return true;
  return DATA_EXTENSIONS.test(value);
}

export function credentialLiterals(code: unknown, _language: CredentialLanguage = "python"): CredentialFinding[] {
  if (typeof code !== "string" || !code) return [];
  const text = code.length > MAX_SCAN_CHARS ? code.slice(0, MAX_SCAN_CHARS) : code;
  const out: CredentialFinding[] = [];
  const seen = new Set<string>();
  const lines = text.split("\n");
  for (let i = 0; i < lines.length && out.length < MAX_FINDINGS; i++) {
    // Fresh matcher per line: a /g regex carries lastIndex between calls.
    const re = new RegExp(LITERAL_RE.source, LITERAL_RE.flags);
    let match: RegExpExecArray | null;
    while ((match = re.exec(lines[i])) !== null) {
      const name = match[1];
      const value = match[3];
      if (looksLikeSource(value)) continue;
      const key = `${name}@${i + 1}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ name, line: i + 1 });
      if (out.length >= MAX_FINDINGS) break;
    }
  }
  return out;
}

/** A stable key for a finding set — the hint's dismissal is scoped to it. */
export function findingsKey(findings: CredentialFinding[]): string {
  return findings.map((f) => `${f.name}@${f.line}`).join("|");
}

/** The bare hostname of the first http(s) literal in the code, or null. */
export function firstHostInCode(code: unknown): string | null {
  if (typeof code !== "string" || !code) return null;
  const match = /https?:\/\/([^\s"'`<>/?#]+)/i.exec(code.slice(0, MAX_SCAN_CHARS));
  if (!match) return null;
  let host = match[1].toLowerCase();
  if (host.includes("@")) host = host.slice(host.lastIndexOf("@") + 1);
  host = host.replace(/:\d+$/, "").replace(/\.$/, "");
  return /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$/.test(host) ? host : null;
}
