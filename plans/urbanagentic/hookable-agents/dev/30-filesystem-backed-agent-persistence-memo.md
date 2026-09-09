# Implementation Memo: Filesystem-Backed Agent Persistence (`DEC-040`)

Date: 2026-07-19 (retroactive record, filed 2026-07-27 — the decision was made conversationally during the first persistence slice and recorded only in the `dev/03` DEC table, the `2.1` register, and `BL-P1-20260719-02`; this memo gives `DEC-040` the same durable memo home every other active decision has)
Status: **implemented** (`BL-P1-20260719-02`; every later persistence slice builds on it)

## 1. Problem Statement

The plan and blueprint said "repository" for the agent lifecycle stores without fixing the medium; the default reading (SQL tables + Alembic migrations) would have added schema/migration weight the rest of Curio's catalog stack doesn't carry. Reuse-first finding during implementation: **datasets and node packages are already filesystem-backed** — only `users` and the project index live in the database.

## 2. Decision — `DEC-040`

Store the agent lifecycle aggregates on the **filesystem**, mirroring the datasets/node-package catalogs:

- definition artifacts under `.curio/users/<key>/agents/<id>@<version>/` (`manifest.json` + `prompts/`);
- account imports ("My Imports") in a per-account JSON registry;
- project-installed templates in the project spec's `dataflow.agents` lockfile;
- attachments in the project/dataflow graph spec.

The database stays limited to users + the project index: **no agent SQL tables, no Alembic migrations**. "Repository" throughout the plan means a filesystem repository (as in `app/datasets/repositories`), never a SQL table.

## 3. As-Built Implementation

`app/agents/{storage,imports,project_agents}.py`, reusing the packages' `_users_base`/`_user_key_segment` roots and `common/safe_paths` containment instead of new path helpers. Path segments (coords, ids) are validated before touching the filesystem.

## 4. Consequences

- Every later store followed the pattern without revisiting the decision: the shared publications catalog (`.curio/agents-catalog/`), prompt-byte materialization, `agentAttachments` + `agentDefaults` spec sections, the session-transcript sidecar (`agent-sessions/`, deliberately *outside* the spec), the account `settings.json`, and the quota counters.
- Spec-resident sections meet client canvas saves — which is why `preserve_agent_state` exists (memo `dev/29`): FS-in-the-spec ownership requires the save handler to protect backend-owned keys.
- Corrupt/missing files read as empty across all stores (a consistent posture set here).

## 5. Traceability

- `BL-P1-20260719-02`; the `DEC-040` rows in `dev/03` §decisions and `2.1` §decisions; cited by nearly every later BL entry.
