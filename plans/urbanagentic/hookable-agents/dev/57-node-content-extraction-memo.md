# Implementation Memo: Node-Content Extraction — Response-Formatting Artifacts Removed (dev/52 follow-up)

Date: 2026-08-05
Status: implemented 2026-08-05 — COMMIT (see log). Verification: backend `pytest tests
--ignore=tests/test_frontend` → 1032 passed; frontend `npx jest` → 660 passed (61 suites).
Note: only the dev/57 hunks of `styles.tsx` were staged — the user's unrelated uncommitted
edits in that file remain untouched.

## 1. Problem Statement

Model replies become node content **verbatim** at several write points; models wrap code in
response formatting, so nodes end up containing ```` ```python … ``` ```` fences, language
identifiers, wrapper objects, and prefixes like "Here is the code:". Affected paths:

1. **Solve** (dev/52): the child's reply text is written directly as the node's content.
2. **`node.create` / `node.template.create` / plan-carried content** (dev/48/52): the model's
   `content` param is minted into proposals as-is.
3. **`node.content.write`** (dev/41): same.
4. **Legacy Get Code** (`generateContentNode` in `styles.tsx`): a crude
   `replaceAll("```json"/"```python"/"```")` that misses other language ids, keeps explanatory
   prose, and corrupts legitimate content containing backticks.

## 2. Approach — one deterministic extractor at every model-output→node-content boundary

`content.extract_node_content(text)` (backend) + `utils/extractNodeContent.ts` (frontend
mirror, replacing the legacy replaceAll):

- **JSON-wrapper unwrap**: a whole-text JSON object carrying a single plausible string field
  (`content`/`code`/`source`/`result`) unwraps (bounded recursion — wrapper-around-fence
  handled).
- **Fence extraction**: when fenced blocks exist, the LARGEST block's body is the content
  (language identifier dropped; prefix/suffix prose outside the fence discarded — that is
  response formatting, not code).
- **Conservative otherwise**: no fences → the text is returned trimmed and untouched. Never
  strips prose heuristically from unfenced content — preserving legitimate code outranks
  cosmetic cleanup; the legacy `not controllable` sentinel passes through exactly.
- Applied at: Solve's child-reply→content write, all three node-content mint branches, plan
  nodes carrying content, and the legacy `generateContentNode` (the crude replaceAll deleted).
- The user's suggestion of an LLM verification agent over generated content is recorded as the
  Validation-agent track (OQ-011) — deterministic extraction is the correct primary mechanism
  (free, reproducible, testable); a semantic checker can layer on later without replacing it.

## 3. Tests / Acceptance

- Unit (both sides): fenced-with-prose, multiple fences (largest wins), ```json / bare fences,
  JSON wrappers, wrapper-around-fence, unwrapped code byte-identical, `not controllable`
  preserved, backtick-free content never altered.
- Routes: Solve writes clean content from a wrapped child reply; a `node.create` proposal
  minted from wrapped params previews and applies clean code.
- [x] Generated node content contains only executable content across Solve, proposals, and the
      legacy Get Code path; unwrapped responses are never altered.

## 4. Commits

1. `Node-content extraction: shared deterministic unwrapper at every generation boundary (dev/57)`
2. Docs: memo implemented + BL-P5 amendment.
