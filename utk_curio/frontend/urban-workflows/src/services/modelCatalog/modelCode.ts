/**
 * The `curio_model("<id>")` grammar, read and written in one place, as
 * `datasetLoaderSnippets.ts` keeps `curio_dataset_path`'s.
 *
 * A node runs a model by naming it in its code. The backend resolves each
 * literal call to the model's folder before the run (`MODEL_CALL_RE` in
 * `backend/app/datasets/domain/code_refs.py`), so the call is the portable
 * reference: no path on this machine ever reaches the code.
 */

/**
 * Model ids are written into Python source, so only an id matching this
 * whitelist may appear inside a `curio_model("<id>")` call: a quote or a
 * backslash would break out of the string literal. KEEP IN SYNC with
 * `MODEL_CALL_RE` in `backend/app/datasets/domain/code_refs.py`, which uses the
 * dataset id charset.
 */
export const SAFE_MODEL_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._@-]{0,199}$/;

/** Same bound as the backend's `MAX_MODEL_IDS`. */
const MAX_MODEL_IDS = 8;

/**
 * Every model id a piece of node code names through a literal
 * `curio_model("<id>")`, first seen first.
 *
 * Both quote styles are accepted because people edit the code; the
 * backreference means a mismatched pair (`curio_model("x')`) names nothing.
 * Mirrors `datasetIdsInCode`, and is kept apart from it: a model is not a
 * dataset, and the backend resolves the two separately.
 */
export function modelIdsInCode(code: unknown): string[] {
  if (typeof code !== "string" || !code.includes("curio_model")) return [];
  const ids: string[] = [];
  // Fresh matcher per call: a module-level /g regex carries lastIndex between
  // calls, so sharing one would make results depend on call order.
  const re = /curio_model\(\s*(["'])([A-Za-z0-9][A-Za-z0-9._@-]{0,199})\1\s*\)/g;
  for (const match of code.matchAll(re)) {
    const id = match[2];
    if (ids.includes(id)) continue;
    ids.push(id);
    if (ids.length >= MAX_MODEL_IDS) break;
  }
  return ids;
}

/**
 * The first literal `curio_model(...)` call that a dropped model can take the
 * place of: a quoted string with no quote, backslash or line break inside.
 * Looser than the id charset on purpose, so a template's placeholder (an empty
 * string, a name with a space) is still the call a drop rewrites.
 */
const REWRITABLE_CALL_RE = /curio_model\(\s*(["'])([^"'\\\r\n]*)\1\s*\)/;

/** True when *code* has a call `rewriteFirstModelCall` can rewrite. */
export function hasRewritableModelCall(code: unknown): boolean {
  return typeof code === "string" && REWRITABLE_CALL_RE.test(code);
}

/**
 * *code* with the id inside its first literal `curio_model(...)` call replaced
 * by *modelId*, in the call's own quote style, or `null` when there is no such
 * call or *modelId* is not safe to write into source.
 */
export function rewriteFirstModelCall(code: string, modelId: string): string | null {
  if (!SAFE_MODEL_ID_RE.test(modelId)) return null;
  const match = REWRITABLE_CALL_RE.exec(code);
  if (!match) return null;
  // Only the id moves: the quotes and any spacing inside the parentheses stay
  // as the author wrote them. `curio_model(` and the spacing hold no quote, so
  // the first one in the match is the opening one.
  const start = match.index + match[0].indexOf(match[1]) + 1;
  return code.slice(0, start) + modelId + code.slice(start + match[2].length);
}
