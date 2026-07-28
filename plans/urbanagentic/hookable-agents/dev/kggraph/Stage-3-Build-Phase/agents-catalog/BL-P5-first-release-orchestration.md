# Build Log — P5: First-Release Agents & Orchestration

Child log for Phase 5 (see `../3.1-Agents-Catalog-Build-Log.md`). Entries follow the
Build Entry Template and are append-only.

---

## BL-P5-20260719-01: Built-in agent definitions (13 prompt-agent migrations) + Global Catalog source

- Date / author: 2026-07-19 / Karla
- Status: verified
- Requirements: `REQ-PROMPT-001` (each prompt behavior → a manifest-defined agent), `REQ-CAT-001` (browsable Global Catalog with real content), `REQ-CAP-001`
- Design decisions/artifacts: `DEC-008` (prompts→hookable agents), `SRC-MEMO-PROMPT-006` (`dev/06` canonical migration map), `DEC-040` (FS-backed)
- Tasks: `TASK-P5-builtin-roster`
- Risks/questions: `RISK-PROMPT-001` (prompt asset resolution), `RISK-PROMPT-003` (the blocked evaluator must not be fabricated)
- Design-to-code decision or deviation: author the 13 releasable built-ins as a **data-driven roster** (`app/agents/builtin.py`) generated from the `dev/06` map + the existing `utk_curio/llm-prompts/*.txt`, rather than 26 hand-written committed files — one source of truth, each entry validated through `parse_agent_manifest`. The Global Catalog scope lists these built-ins; Import/Install resolve a coord from the user store **or** the built-in roster. `agent.generated-content-evaluator` is intentionally excluded (no prompt file — blocked by `OQ-007`). Prompt-byte materialization into a user store (copying from `llm-prompts/`) is a follow-up; catalog cards + import/install coords don't need it.
- Files/modules changed:
  - `utk_curio/backend/app/agents/builtin.py` (new — 13-agent roster + manifest generation + coord resolution; `PROMPT_SOURCE_DIR` → `utk_curio/llm-prompts/`)
  - `utk_curio/backend/app/agents/services.py` (`list_global_catalog`; `_resolve_definition` = store ∪ built-in roster)
  - `utk_curio/backend/app/agents/routes.py` (`GET /api/agents/catalog`)
  - `utk_curio/backend/tests/test_agents/test_builtin.py` (new), `test_routes.py` (catalog + built-in import/install)
  - `docs/AGENTS.md` (§6 Global Catalog = 13 built-ins)
- Tests added/updated: `TEST-P5-builtin` = `tests/test_agents/test_builtin.py` (roster ↔ dev/06 map, prompt files exist, 13 manifests validate); catalog route tests in `test_routes.py`
- Verification evidence: `pytest test_agents/ test_llm_default_provider.py` → 79 passed. `GET /api/agents/catalog` returns 13 built-in cards; a built-in imports/installs without a prior store copy; evaluator absent.
- Commit/PR: `COMMIT-6412bff`
- Issues/regressions discovered: initial `PROMPT_SOURCE_DIR` used `parents[2]` (backend/) — fixed to `parents[3]` (utk_curio/); caught by `test_every_prompt_file_exists`.
- Resolution: path corrected; all prompt files resolve.
- Follow-up work: materialize built-in prompt bytes into the user store on install; orchestration/composite agents (P5 remainder, v2); imported-only Publish.
- Remaining risks/questions: built-in prompt path is nominal until materialization; categories/hooks assigned per a small mapping (refine against final UX).

**Amendment (2026-07-27, memo `dev/38`):** the roster manifests were missing the `dev/05` System-file column and `inputs` — every built-in now declares `prompts.system` (`default_preamble.txt`; the syntax agent its own preamble) and grounded `inputs.reads` (from each legacy call site's actual context); install materializes both assets; and the run path restores the legacy `preamble + prompt` composition (`dev/06` parity — an edited intent replaces the instruction portion only). Tests: `TestPreambleAndInputs`, `TestMaterializePreamble`, updated run-path assertions; 245 agents tests green.
