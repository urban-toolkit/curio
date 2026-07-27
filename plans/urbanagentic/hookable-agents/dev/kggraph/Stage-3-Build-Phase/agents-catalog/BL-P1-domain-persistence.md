# Build Log — P1: Domain & Persistence

Child log for Phase 1 (see `../3.1-Agents-Catalog-Build-Log.md`). Entries follow the
Build Entry Template and are append-only.

> **Backfill note.** Entries `BL-P1-20260719-01` and `-02` were written retroactively,
> immediately after the first commits, once the per-change build-log discipline was
> restored. Going forward an entry is created with (not after) each change per
> Tracking Rule 1. Prior history is not erased.

---

## BL-P1-20260719-01: Agent manifest schema + validator

- Date / author: 2026-07-19 / Karla
- Status: verified
- Requirements: `REQ-PROMPT-001` (versioned manifest, typed I/O, digest-verified prompt links), `REQ-CAP-001` (semantic capability contracts)
- Design decisions/artifacts: `DEC-008`; `SRC-MANIFEST-011`; `SRC-BLUEPRINT-005`; new artifact `docs/schemas/agent-package.v1.json` (canonical schema)
- Tasks: `TASK-P1-manifest` — define the agent-package.v1 schema + backend validator
- Risks/questions: `RISK-PROMPT-001` (missing/escaping/mismatched prompt asset), `RISK-CAP-001` (prompt filenames becoming capability ids)
- Design-to-code decision or deviation: mirrored the node-package validator (`app/packages/manifest.py`) with hand-rolled `from_json` validation and `{where}.field` errors instead of adding a `jsonschema` dependency — reuse-first, matches the existing codebase pattern.
- Files/modules changed:
  - `docs/schemas/agent-package.v1.json` (new — canonical camelCase manifest schema)
  - `utk_curio/backend/app/agents/__init__.py` (new module)
  - `utk_curio/backend/app/agents/manifest.py` (new — `AgentManifest` + capability/prompt/target/tool dataclasses, `parse_agent_manifest`, `load_agent_manifest`)
  - `docs/AGENTS.md` (new §§1–3 + validator appendix)
- Tests added/updated: `TEST-P1-manifest` = `utk_curio/backend/tests/test_agents/test_manifest.py` (31 tests)
- Verification evidence: `pytest test_agents/test_manifest.py` → 31 passed. Capability-id rules verified (rejects `_prompt`/`.txt`/path/underscore/single-segment/dup), prompt-path containment (absolute + `..` escape blocked), `agent.`+semver grammar, dir/manifest agreement.
- Commit/PR: `COMMIT-6ca43c4`
- Issues/regressions discovered: none
- Resolution: n/a
- Follow-up work: the definition artifact store consumes `load_agent_manifest` (see `-02`).
- Remaining risks/questions: capability taxonomy enumeration deferred (`dev/08`); prompt-byte digest verification deferred to the install path.

---

## BL-P1-20260719-02: Filesystem-backed definition / import / project-template storage

- Date / author: 2026-07-19 / Karla
- Status: verified
- Requirements: `REQ-IMPORT-002`, `REQ-PROJECT-INSTALL-001`; realizes the `DEC-029` aggregates on disk
- Design decisions/artifacts: **`DEC-040`** (filesystem-backed lifecycle; no agent SQL tables / no Alembic migrations); `SRC-BLUEPRINT-005`; reuse of `app/datasets/repositories` + `app/packages/storage`
- Tasks: `TASK-P1-storage` — definition store, My Imports registry, project-template lockfile
- Risks/questions: `RISK-PRIVACY-001` (cross-account/project exposure), `RISK-IMPORT-001` (path traversal/escape), `RISK-SCOPE-001` (project state leak)
- Design-to-code decision or deviation: `DEC-040` — reuse-first finding that datasets/packages are filesystem-backed and only `users`/`projects` use the DB. Agent lifecycle stored on the filesystem (no migration). Reused packages `_users_base`/`_user_key_segment` roots and `common/safe_paths` containment rather than new helpers.
- Files/modules changed:
  - `utk_curio/backend/app/agents/storage.py` (new — definition store under `.curio/users/<key>/agents/<id>@<version>/`)
  - `utk_curio/backend/app/agents/imports.py` (new — account "My Imports" registry JSON)
  - `utk_curio/backend/app/agents/project_agents.py` (new — `spec['dataflow']['agents']` lockfile)
  - `docs/AGENTS.md` (new §5 — storage layers)
- Tests added/updated: `TEST-P1-storage` = `utk_curio/backend/tests/test_agents/test_storage.py` (15 tests)
- Verification evidence: `pytest test_agents/` → 46 passed. Path traversal blocked; missing/corrupt tolerated (skip-not-fatal); import add/remove/idempotent/corrupt; lockfile read/write/filter/sort.
- Commit/PR: `COMMIT-7458300`
- Issues/regressions discovered: none
- Resolution: n/a
- Follow-up work: Import/Install/Publish routes (P3) call these repositories; attachment records live in the graph spec (P4).
- Remaining risks/questions: the deferred encrypted-secret store (2b) can also be an encrypted FS file — no migration required.
