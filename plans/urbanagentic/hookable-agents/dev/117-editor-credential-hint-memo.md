# dev/117 — The last way a key reaches a saved dataflow is a person typing it into the node editor: hint, never block, and offer the connection-key route where the key is being pasted

**Status: IMPLEMENTED (2026-09-09) on `imp/agentcatalog` — commits `5e0177b3` (1, `services/connectionKeys/credentialLiterals.ts` + shared fixtures on both sides + `suggestName`/`hostOf` on the request bus, fixing the dev/116 copy's last-path-segment bug), `1cfd63b2` (2, `CredentialHint` bar + `CodeEditor` wiring: 300 ms debounce on typing, immediate scan on `onExternalApply`, dismissal keyed on `findingsKey`, best-effort Monaco Warning markers, guard scope), `49de270d` (3, docs: `docs/USAGE.md`, `docs/AGENT-CATALOG.md`; ledgers in the untracked `plans/` tree: dev/00 row, `BL-P5-20260909-51`, `3.1`, dev/116 F4 closure). No new DEC. Suites: jest 202 suites / 2345 tests, backend `test_source_grounding.py` 42 passed, `tsc` clean. Deviations, recorded in `BL-P5-20260909-51`: the guard takes the new stylesheet as an explicit extra file (the rest of `components/editing` is legacy CSS with literals of its own); a moved literal re-shows a dismissed hint (accepted for simplicity). Owner questions resolved by default: every Python/JS code editor, markers on, dismissal per mount.**

Date: 2026-09-09
Branch / tree: `imp/agentcatalog` @ `83c7a34b` (dev/116 closed, dev/115 F6 closed). Line numbers pinned to that commit. `plans/` is untracked on this branch (a staged snapshot of it exists in the index, not authored by this memo's sessions) — this memo lives on disk.
Origin: dev/116 follow-up **F4** (*"editor-side hint when a user types a credential literal into node code"*), chosen by the owner 2026-09-09 as the first of the three remaining follow-ups (*"lets plan the editor hint first"*), over the Streetvision Maps key (F2) and the T4 encrypted store (F1).
Evidence: `agents/source_grounding.py:86-100` — the runtime's credential-literal detector: `_CRED_NAME_RE` (an assignment target, dict key or keyword named like `api_key`, `token`, `Authorization`…), `_CRED_VALUE_RE` (one token, ≥ 20 chars of `[A-Za-z0-9_\-.~+/=]`, optional `Bearer `), `_CRED_LITERAL_FALLBACK_RE` (the regex form for non-Python content); `credential_literals(code, engine)` at `:538`. It refuses **agent-authored** content before anything runs (dev/116, DEC-074) — and is never consulted for the code a user types: `api/routes.py` `/processPythonCode` runs the user's code as written (the user's code is theirs, by design). `components/editing/CodeEditor.tsx:60-115` — the Monaco model is the source of truth; `handleCodeChange` (`:92-95`) only mirrors it to `code` and marks the node stale; external content arrives through `useMonacoExternalValue` (`:77-83`, dev/70) whose `onExternalApply` is the one hook every non-typed change passes through (dataset drop, LLM apply, provenance navigation, collab apply). `CodeEditor.tsx:351-385` — the editor already has a bar above Monaco for a collab proposal, inline-styled with colour literals (`#fff8e1`, `#e3f2fd`) — the shape to reuse, not the styling. `CodeEditor.tsx:397` — the language is `javascript` for JS computation nodes, `python` otherwise. No `setModelMarkers`/`deltaDecorations` call exists anywhere in the frontend: the editor has never annotated a line. `services/datasetCatalog/datasetLoaderSnippets.ts:40-60` — the precedent for a frontend twin of a backend regex kept in sync by comment (`curio_dataset_path`), with a bounded scan. `components/connectionKeys/connectionKeysRequest.ts` — `requestConnectionKeys({host, suggestedName})` opens Settings → Connection keys from anywhere; `ConnectionKeysModalHost` answers it on the canvas (dev/116 commit 4). `tests/components/editing/CodeEditor.test.tsx:1-60` — the fake Monaco (`__type` fires `onChange` like real typing; `onMount` receives a stub `monaco` with `KeyMod`/`KeyCode` only). `tests/styles/agentColourLiterals.test.ts:23-27` — the colour-literal guard walks `components/agents` and the agents palette only; `components/editing` is outside it.
Family: dev/70 (uncontrolled Monaco, `useMonacoExternalValue`) → dev/114 (DEC-072 gate: agents never invent a source) → dev/116 (DEC-074: connection keys; the gate refuses a credential literal from an agent; `AddKeyAction`; the request bus) → **dev/117**.
Design decisions consumed: DEC-072 (the gate covers agent-authored content — this memo covers the human's, without a gate), DEC-074 (a key is reached by name; the value is never written into a node). **No new DEC**: a non-blocking editor hint inside DEC-074's posture, recorded in the backlog like dev/96 was.
Backlog: `BL-P5-20260909-51` at closure; closes dev/116 F4.

---

## 1. Problem Statement

**What is missing.** dev/116 made every *agent* path safe: a credential-shaped literal in agent-authored code is refused before it runs, and the loop offers a connection key instead. The one path left is the person: paste `api_key = "…"` into a node's code, press Play, and the key is in the saved dataflow, in the runtime journal, in every export and in every proposal preview that later quotes the node — silently. Nothing in the editor says a word.

**Where it shows.** The code editor of every Python or JavaScript node (`CodeEditor.tsx`). Both entry paths: typing/pasting (`handleCodeChange`) and content arriving from elsewhere (`onExternalApply`: a dataset drop, an LLM apply, a peer's collab change, provenance navigation).

**Expected behavior.** When the code contains a credential-shaped literal, a quiet bar appears above the editor: *"Line 4 looks like an API key. Keys in node code are saved with the dataflow and shared with it. Save it as a connection key and write `api_key = curio_secret("<name>")` instead."* with **Save as connection key** (opens Settings → Connection keys, host prefilled from the code's URL when there is one) and **Dismiss**. The line gets a warning marker where Monaco supports it. Nothing is blocked: Play, save and collab work exactly as today; the code is never changed by the hint; the value never leaves the editor. Removing the literal removes the hint; dismissing hides it for that literal in that node until a *different* literal appears.

**Why it matters.** It closes the last leak path with the cheapest possible intervention, at the moment the leak is about to happen, pointing at the mechanism that already exists. It is a hint and never a block because the user's own code is theirs (DEC-072's line), and because the detector is a heuristic: a long opaque ID assigned to a variable named `key` is a legitimate thing to write.

## 2. Scope

**Included**

- **One detector, mirrored**: `services/connectionKeys/credentialLiterals.ts` — `credentialLiterals(code, language) -> Array<{name, line, column?}>`, the TypeScript twin of the backend's regex form (`_CRED_LITERAL_FALLBACK_RE` + `_CRED_VALUE_RE`, plus the JS shapes `const|let|var key = "…"` and `{ key: "…" }`), bounded (first 5 findings, scan capped at 200 KB), never returning the value. A `KEEP IN SYNC` comment on both sides (the `datasetLoaderSnippets.ts` precedent) **and** a pinned fixture list — the same positive/negative strings asserted in `test_source_grounding.py` and in the frontend test — so the two detectors cannot drift apart unnoticed.
- **The hint bar** in `CodeEditor.tsx`: a `CredentialHint` component (`components/editing/CredentialHint.tsx` + `CredentialHint.module.css`, tokens only) rendered above Monaco when findings exist and are not dismissed; copy per §5; **Save as connection key** calls `requestConnectionKeys({host, suggestedName})` with the host taken from the first `https?://` literal in the code (bare hostname; `suggestedName` from its second-level label, the dev/116 rule) or no host when none; **Dismiss** hides it for the current finding set.
- **Detection timing**: on `handleCodeChange` debounced 300 ms (typing) and immediately on `onExternalApply` (content that arrives whole); cleared when findings vanish.
- **Line markers, best-effort**: on mount keep the `monaco` instance; when `monaco.editor?.setModelMarkers` exists, set one `Warning` marker per finding (owner `curio-credential`, message = the hint's first sentence) and clear them when findings vanish. Absent in the test fake → skipped, the bar still renders.
- **Read-only editors**: the bar renders text only (no Save action, no Dismiss needed); a viewer of a shared dataflow learns the risk without a form they cannot use.
- **Docs on close** (dev/93 convention): `docs/USAGE.md` Connection keys section gains one paragraph (the editor hint and what it does not do); `docs/AGENT-CATALOG.md` key-gated section gains one sentence; dev/00 row, `BL-P5-20260909-51`, `3.1`, dev/116 F4 closure.

**Must be checked but not changed**

- `useMonacoExternalValue` (dev/70) — untouched; the detector subscribes to its `onExternalApply` callback that `CodeEditor` already owns.
- The collab proposal bar — unchanged; the hint bar sits beside it (both may show).
- `/processPythonCode`, the runtime journal, Play — unchanged; nothing is blocked or rewritten.
- The backend detector — unchanged in behaviour; its test gains the shared fixture list.
- `GrammarEditor.tsx` (Vega/Autark JSON) — out of scope v1 (a key in a Vega spec URL is rare; recorded as follow-up).

**Out of scope (explicitly)**

- Blocking Play or save on a detected literal — never (the user's code is theirs; the detector is a heuristic).
- Rewriting the code for the user (replacing the literal with `curio_secret(...)`) — a later "fix it" action once the key is saved; not v1 (it would need the saved name and a confident edit).
- Scanning the saved dataflow at load time or on the Projects page — a different surface.
- Any telemetry, logging or transmission of the finding — the finding stays in the browser tab.
- The Streetvision Maps key (F2) and the encrypted store (F1).

## 3. Recommended Implementation Approach

### 3.1 The detector (pure, mirrored, bounded)

```ts
// services/connectionKeys/credentialLiterals.ts
export interface CredentialFinding { name: string; line: number; }
export function credentialLiterals(code: string, language: "python" | "javascript"): CredentialFinding[]
export function firstHostInCode(code: string): string | null   // bare hostname of the first http(s) literal
```

Regex form only (the backend's `ast` form is not portable, and its regex fallback is the shared shape): `(?<name>api[_-]?key|apikey|key|token|access[_-]?token|secret|password|authorization|x-api-key)["']?\s*[:=]\s*["'](?<value>(?:Bearer\s+)?[A-Za-z0-9_\-.~+/=]{20,})["']`, case-insensitive, per line; JS adds `(?:const|let|var)\s+` before the name. Excluded by construction: values that are URLs or paths (`://`, `/`-rooted, extension-shaped — the backend's `classify_literal` twin is three checks), `curio_secret(...)` calls (never a quoted literal value), `os.environ[...]`. The value is matched and dropped; only `name` and `line` leave the function. Bounded: stop at 5 findings; ignore code beyond 200 KB.

### 3.2 The bar

`CredentialHint` receives `findings`, `readOnly`, `host`, `onDismiss`. Copy (§5) names the first line and the count when more than one (*"Lines 4 and 9 look like API keys"*). **Save as connection key** → `requestConnectionKeys({ host: host ?? undefined, suggestedName: host ? suggestName(host) : undefined })` — the dev/116 bus; `ConnectionKeysModalHost` on the dock overlay opens the section. `suggestName` moves from `ConnectionKeysSection.tsx` into `connectionKeysRequest.ts` (one implementation, both callers). Styles: `CredentialHint.module.css`, tokens only (`--curio-warning-bg`/`--curio-warning-text` or the closest existing pair — checked against the token sheet at implementation), and `components/editing` is added to the colour-literal guard's directory list for **this stylesheet only** (the guard walks whole directories; the inline-styled legacy of `CodeEditor.tsx` stays out of it — a `.module.css` is what the guard reads).

### 3.3 Wiring in `CodeEditor.tsx`

- `const [findings, setFindings] = useState<CredentialFinding[]>([])`, `const [dismissedKey, setDismissedKey] = useState<string | null>(null)`.
- `scheduleScan(value)`: debounced 300 ms → `setFindings(credentialLiterals(value, language))`; called from `handleCodeChange`; `onExternalApply` calls the scan immediately (content arrived whole).
- `findingsKey = findings.map(f => \`${f.name}@${f.line}\`).join("|")`; the bar renders when `findings.length && dismissedKey !== findingsKey`; Dismiss sets `dismissedKey = findingsKey` — a new or moved literal shows again (a moved line is a small cost worth the simplicity; §6.7).
- Markers: `monacoRef.current?.editor?.setModelMarkers?.(model, "curio-credential", findings.map(…))`, and `[]` when none; guarded so the fake and older Monaco builds skip it.
- Unmount: clear markers.

### 3.4 What this is NOT

Not a gate (no refusal, no disabled Play). Not a rewrite (no edit to the model). Not persistent (dismissal is per mount; a reload shows the hint again — deliberate: a key still in the code is still a leak). Not a scan of anything but the editor's own content.

## 4. Data and State Handling

- **Source of truth**: the Monaco model's text (via the existing `onChange`/`onExternalApply` paths). Derived: `findings` (debounced), `findingsKey`, `dismissed`.
- **States**: none → no bar; findings → bar (+ markers); dismissed → no bar until `findingsKey` changes; read-only → text-only bar.
- **After actions**: Save as connection key opens the modal and leaves the editor untouched; when the user later replaces the literal with `curio_secret("…")`, the next scan clears the bar and the markers.
- **Races**: the debounce timer is cleared on unmount and on each keystroke; an external apply cancels a pending typed scan and scans at once; a stale scan result cannot arrive after unmount (guarded by a mounted ref).
- **No duplication**: one detector, one `suggestName`, one request bus, one bar component.

## 5. UI and UX Requirements

- Bar above the editor, same height class as the collab bar; icon-free, text first: **"Line 4 looks like an API key."** then *"Keys in node code are saved with the dataflow and shared with it. Save it as a connection key and write `api_key = curio_secret("<name>")` instead."* Plural form when several lines.
- Buttons: **Save as connection key** (primary-quiet), **Dismiss** (ghost). In read-only editors: text only.
- The Monaco marker: severity Warning, message *"Looks like an API key — use a connection key (curio_secret) instead."*, squiggle under the line — never an error squiggle (nothing is wrong with the syntax).
- Accessibility: the bar is `role="status"` with `aria-live="polite"` (it appears as a consequence of typing, not as an interruption); buttons have full-sentence `aria-label`s (*"Save this key as a connection key"*, *"Dismiss this hint"*); the line number is in the text, not only in the marker; colour is never the only signal.
- No flicker: the bar mounts once findings settle (debounced), does not re-mount per keystroke, and does not push the editor's cursor (the editor is `flex: 2, minHeight: 0`; the bar takes its own row).

## 6. Edge Cases

1. **Pasting a whole file with several keys** — first 5 findings; the copy names the first line and the count.
2. **A key inside a comment** — detected (still saved with the dataflow); the hint applies.
3. **`os.environ["KEY"]`, `curio_secret("census")`, `key = some_var`** — not literals; no hint.
4. **A URL or path assigned to `key`** — excluded by the value classifier; no hint. **A long opaque ID** (`key = "abc123…"` 20+ chars) — hinted; acceptable, the hint is dismissable and non-blocking (stated).
5. **Starter code placeholders** (`YOUR_API_KEY_HERE`, 17 chars) — below the length bound; no hint. A placeholder shaped like a key (`sk-xxxxxxxxxxxxxxxxxxxx`) — hinted; fine.
6. **Content arriving from an agent apply** — an agent cannot produce a credential literal past the gate, so this fires only for legacy/imported content; when it does, the hint is right.
7. **Editing moves the literal to another line** — `findingsKey` changes, a dismissed hint reappears; accepted for simplicity (§3.3).
8. **Collab: a peer's applied change contains a key** — the hint shows for the receiver too (text + actions); nothing is sent back.
9. **Read-only editor** — text-only bar.
10. **Very large content** — scan capped at 200 KB; beyond that no scan, no hint (stated in a code comment, not to the user).
11. **Monaco without `setModelMarkers`** (tests, unexpected builds) — bar only.
12. **JS nodes** — the JS shapes are detected; the copy is identical.
13. **Unmount mid-debounce** — timer cleared; no state update after unmount.

## 7. Testing Strategy

**Frontend (jest, required)**

- `services/connectionKeys/credentialLiterals.test.ts`: the shared fixture list — positives (Python assignment, dict entry, kwarg, `Authorization: "Bearer …"`, JS `const key = "…"`, object literal) and negatives (URL value, path value, `curio_secret("x")`, `os.environ[...]`, short value, non-credential name with a long value); bounds (5 findings, 200 KB); `firstHostInCode`.
- `components/editing/CodeEditor.test.tsx`: typing a key shows the bar after the debounce (fake timers) with the line number; removing it hides the bar; Dismiss hides it and a different literal re-shows it; **Save as connection key** dispatches the request with the host from the code's URL and the suggested name; an external apply (dataset drop / LLM apply path through `onExternalApply`) shows the bar immediately; read-only renders text only; markers are set and cleared when the fake Monaco exposes `setModelMarkers`, and skipped when it does not; the collab bar and the hint bar coexist.
- `tests/styles/agentColourLiterals.test.ts`: `components/editing/CredentialHint.module.css` is inside the guard's walk (directory list gains `components/editing` **or** the single file — decide at implementation; the legacy inline styles of `CodeEditor.tsx` are not stylesheets and are unaffected).
- `tsc --noEmit` clean.

**Backend (required, one change)**

- `test_source_grounding.py::TestConnectionKeys::test_credential_literals_are_found_by_shape_never_returned` gains the same fixture strings as the frontend test (a comment names the twin), so a change to either detector fails a test on the other side's fixtures.

## 8. Acceptance Criteria

1. Typing `api_key = "<20+ token chars>"` into a Python node's editor shows, within half a second, a bar naming the line and offering **Save as connection key** and **Dismiss**; Play and save are unaffected.
2. The same for a JS node with `const token = "…"`.
3. Clicking **Save as connection key** opens Settings → Connection keys with the host from the code's URL prefilled (when the code has one) and a suggested name.
4. Deleting the literal or replacing it with `curio_secret("<name>")` removes the bar and the marker.
5. **Dismiss** hides the bar for that literal; a different literal shows it again; a reload shows it again.
6. `curio_secret("census")`, `os.environ["KEY"]`, URLs and paths assigned to `key`, and values under 20 characters never show the bar.
7. Content that arrives through an apply (dataset drop, LLM apply, collab) is scanned immediately.
8. The finding never leaves the browser tab: no request carries the literal or its line.
9. The frontend and backend detectors agree on the shared fixture list.
10. `docs/USAGE.md` describes the hint in one paragraph; the backlog entry and dev/116 F4 record the closure.

## 9. Recommended Commit Breakdown

- **Commit 1 — detector + fixtures**: `credentialLiterals.ts`, `firstHostInCode`, `suggestName` moved into `connectionKeysRequest.ts`, the frontend fixture test; the backend test gains the same fixtures (and the `KEEP IN SYNC` comments on both regexes).
- **Commit 2 — the bar and the wiring**: `CredentialHint.tsx` + `.module.css`, `CodeEditor.tsx` scan/debounce/dismiss/markers, the colour-literal guard scope, the `CodeEditor` tests.
- **Commit 3 — docs + ledgers**: `docs/USAGE.md`, `docs/AGENT-CATALOG.md`; `plans/` (untracked): dev/00 row, `BL-P5-20260909-51`, `3.1`, dev/116 F4 closure, this memo's status.

## 10. Engineering Quality Checklist

- One detector (TS) mirroring one backend shape, with shared fixtures on both sides; one `suggestName`; one request bus; one bar component.
- The value is matched and dropped — never stored, never rendered, never sent.
- Types explicit (`CredentialFinding`); the language parameter is the editor's own.
- Debounced scan, cleared on unmount; immediate scan on external apply; no per-keystroke re-mount.
- Tokens only in the new stylesheet; the guard covers it.
- Non-blocking by construction: no code path from the hint into Play, save or the model's text.
- Accessibility: `role="status"`, `aria-live="polite"`, sentence labels, line number in text.
- Tests: detector fixtures (both sides), bar behaviour (show/hide/dismiss/action/read-only/markers/external apply), guard scope, `tsc`.
- Follows dev/70's editor discipline (never a controlled `value`), dev/116's request bus, and the `datasetLoaderSnippets` twin-regex precedent.

## Open questions for the owner (non-blocking — defaults stated)

1. **Scope of nodes**: every Python/JS code editor (default — a key leaks from any node) vs data-loading nodes only.
2. **Markers**: line squiggles on top of the bar (default: yes, best-effort) or the bar alone.
3. **Dismissal memory**: per mount (default — a reload shows it again while the key is still there) or remembered per node in `localStorage`.

## Follow-ups (recorded, not delivered)

- **F1** A "Replace with `curio_secret("<name>")`" action once a key with a matching host is saved — a confident, reviewable edit of the user's own code.
- **F2** The same hint in `GrammarEditor.tsx` (Vega/Autark specs with keyed data URLs).
- **F3** dev/116 F2 (Streetvision Maps key) and F1 (the encrypted store) — unchanged here.
