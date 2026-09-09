# Implementation Memo: Upload-Import — User-Authored Agent Definitions

Date: 2026-07-27
Status: **implemented** (2026-07-27; `BL-P3-20260727-10` — commits `c630c01` backend, `018df3d` frontend)
Feature slice: v2 entry (`DEC-038`) — activates the already-built Publish path by creating the first user-**owned** definitions
Design sources: memo `12` (explicit account import; imported-only publish, `DEC-030`), `DEC-029` (immutable definition artifacts), `DEC-040`/`dev/30` (FS store), `RISK-IMPORT-001` (hostile-archive mitigations), concept `png-concepts/01` (the drawer's `Import package` button), rule 7 (collision behavior must be recorded)

## 1. Problem Statement

Users cannot author agents. The store only ever holds materialized built-ins (`trust: "built-in"`), which are deliberately non-publishable, so the entire Publish path — endpoint, eligibility gating, Catalog Hub store, drawer pill — has been live but unreachable since `BL-P3-…-06`. Upload-import creates owned (`trust: "imported"`) definitions with their own prompt bytes, making Publish user-reachable end-to-end and giving the future governance stack real content to govern.

## 2. Scope and the Key Security Decision

**JSON-body upload, not archives.** `RISK-IMPORT-001` enumerates the archive attack surface (symlinks/special files, expansion bombs, partial visibility). This slice avoids that surface entirely: the upload is a JSON payload — `{"manifest": {...}, "prompts": {"prompts/x.txt": "<text>", ...}}` — assembled client-side from individually picked `manifest.json` + `.txt` files. No extraction, no filesystem semantics from user input beyond validated relative paths. Zip/archive upload, if ever wanted, is a later P6-hardened addition.

**In scope:** `POST /api/agents/imports/upload`, service validation + atomic store write, My Imports registration, the drawer's `Import package` button + `AgentImportModal`, tests including the full upload→publish→install→attach→run loop.
**Out of scope:** archive upload; editing an uploaded definition (immutable — re-upload a new version; prompt *drafting* is v2 governance); any auto-install/auto-publish (nothing chains, `DEC-030`).

## 3. Server Rules (all fail-closed)

1. **Manifest contract**: the payload manifest must pass `parse_agent_manifest` (agent-id prefix, capabilities, contained prompt paths, etc.).
2. **Forced provenance**: `provenance.trust` is **overwritten server-side to `"imported"`** regardless of what the payload claims — an upload asserting `built-in`/`global` trust must never corrupt publish gating or roster-first resolution.
3. **Digests from bytes**: the server computes each prompt asset's `sha256` from the uploaded text and stamps it into the stored manifest (the bytes are the truth; client-supplied digests are ignored).
4. **Exact file correspondence**: the provided prompt files must match the manifest's referenced prompt paths exactly — a missing referenced file or an extra unreferenced file is a 400.
5. **Limits**: ≤ 16 prompt files, ≤ 256 KB per file, ≤ 1 MB total prompt bytes (413 on breach).
6. **Collision = immutability** (rule 7): a coordinate already present in the user's store is a **409** — definitions are immutable (`DEC-029`); bump the version instead. Shadowing a *built-in* coordinate is allowed by the existing resolution rules (an owned store definition deliberately wins), and materialized built-ins count as store presence → 409, which also prevents silently replacing a built-in you installed.
7. **Atomic commit**: bytes are staged in a temp directory inside the user's agents store and `os.replace`d into the final coordinate directory — no partially visible artifact (the JSON-slice remnant of `RISK-IMPORT-001`'s mitigations that still applies).
8. **Registration**: success adds the coordinate to My Imports (upload **is** an explicit account import) and returns the My Imports card — `publishable: true` for the first time.

## 4. Frontend

An **`Import package`** button in the drawer footer (per concept `01`) opens `AgentImportModal`: a multi-file picker (`manifest.json` + `.txt` prompt files), assembled by a pure `buildUploadPayload` helper (`.txt` files become `prompts/<name>`), a summary of what will be imported, server errors shown verbatim (they are field-specific), and on success the drawer switches to My Imports and reloads — where the new card shows `Install` and the live Publish pill.

## 5. Testing

Backend: happy path (files on disk, digests stamped, card publishable); **the full loop** — upload → publish → appears in the Global Catalog → install → attach → run with the uploaded instruction as the system turn; forced-trust (payload claiming `built-in` stores as `imported` and is publishable); duplicate coordinate 409 (incl. after materializing a built-in); missing/extra prompt file 400; traversal-shaped prompt path rejected; size limits 413; malformed manifest/prompts 400.
Frontend: `buildUploadPayload` unit tests; modal render/submit/error tests with `File` objects; drawer button wiring; api-client test.

## 6. Acceptance Criteria

- [ ] A user can upload a valid manifest + prompt texts and immediately see an owned My Imports card with working `Install` and `Publish`.
- [ ] The published definition appears in other accounts' Global Catalog, installs, attaches, and runs from its own uploaded prompt bytes.
- [ ] No upload can create a non-`imported` trust, overwrite an existing store artifact, plant a file outside the definition directory, or exceed the size limits.
- [ ] Nothing auto-chains: upload only imports; Install and Publish remain separate explicit actions.
- [ ] All existing suites pass.
