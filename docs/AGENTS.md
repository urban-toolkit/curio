# Hookable Agents

Hookable agents are Curio's reusable AI building blocks. Like a node package, an agent is a small, self-contained folder with a `manifest.json` describing what it does — but instead of a canvas node, it defines an assistant you can attach to a node, a connection, or the whole canvas, and refine in chat.

> **Status: in active development.** This document grows as the feature lands. Today it covers the **agent manifest contract** — the schema and validator every agent package is built on. The catalog drawer, install/attach lifecycle, and chat surfaces are documented here as each ships.

This guide is in parts, plus a developer appendix:

- [1. What is a hookable agent?](#1-what-is-a-hookable-agent) — the model and how it relates to node packages.
- [2. The agent manifest](#2-the-agent-manifest) — the `manifest.json` contract, field by field.
- [3. Capabilities](#3-capabilities) — semantic behavior contracts, and why they are never prompt filenames.
- [4. The default LLM provider](#4-the-default-llm-provider) — the single default every agent (and the LLM chat) falls back to.
- [Appendix: validating a manifest (developer-only)](#appendix-validating-a-manifest-developer-only).

---

## 1. What is a hookable agent?

Every agent Curio knows about ships as an **agent package**, identified by an id and a version:

```
<agentId>@<version>     e.g.   agent.node-explainer@1.0.0
                             agent.dataflow-builder@1.0.0
```

Agent package ids always begin with **`agent.`**, which keeps them distinct from node package ids (`curio.builtin`, `ai.urbanlab.uhvi`) and other product namespaces. A package is a folder with a `manifest.json` (the contract) and a `prompts/` directory holding the system preamble and instruction assets the manifest references by digest.

Agents follow the same **catalog model** as node packages and datasets — you browse a shared catalog, import/install into your own scope, and (for definitions you own) publish back to the catalog hub. The manifest is the foundation that model is built on; this document starts there.

| Concept | Node package | Hookable agent |
|---|---|---|
| Ships as | `<packageId>@<major>/` with `manifest.json` | `<agentId>@<version>/` with `manifest.json` + `prompts/` |
| Id namespace | `curio.builtin`, `ai.urbanlab.uhvi` | `agent.node-explainer`, `agent.dataflow-builder` |
| Provides | Draggable canvas node kinds | An assistant attachable to a node / connection / canvas |
| Canonical schema | [`docs/schemas/node-package.v4.json`](schemas/node-package.v4.json) | [`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json) |

---

## 2. The agent manifest

The manifest uses **camelCase** field names and is validated against [`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json) (JSON Schema Draft 2020-12). The schema is the source of truth for what fields a manifest can declare.

A minimal, complete manifest:

```json
{
  "$schema": "../../docs/schemas/agent-package.v1.json",
  "id": "agent.node-explainer",
  "name": "Node Explainer",
  "category": "node",
  "version": "1.0.0",
  "purpose": "Explain what a node or its output does.",
  "roles": ["explanation"],
  "capabilities": [
    { "id": "node.explain", "contractVersion": "1" },
    { "id": "node.output.interpret", "contractVersion": "1" }
  ],
  "delegatesTo": [],
  "prompts": {
    "system": { "path": "prompts/default_preamble.txt", "sha256": "<sha256>", "variables": [] },
    "instruction": { "path": "prompts/single_box_explanation.txt", "sha256": "<sha256>", "variables": ["nodeContext"] }
  },
  "compatibleTargets": [{ "kind": "node", "requires": ["code-or-output"] }],
  "inputs": { "reads": ["nodeContext"], "requiredConfig": [] },
  "outputs": ["explanation"],
  "runtime": { "execution": "foreground", "reviewPolicy": "report-only" },
  "providerRequirements": { "capabilities": ["structured-output"] },
  "tools": [{ "id": "catalog.search", "required": false }],
  "settingsDefaults": { "profileId": "interactive-report", "profileVersion": "1" },
  "provenance": { "publisher": "curio", "license": "MIT", "trust": "built-in" }
}
```

| Field | Required | What it declares |
|---|---|---|
| `id` | ✓ | `agent.`-prefixed, kebab-case package id. Pairs with `version` to form the on-disk directory `<id>@<version>`. |
| `version` | ✓ | Semver-style version string. |
| `name` | ✓ | Human-readable name shown in the catalog. |
| `category` | ✓ | One of `data`, `node`, `canvas`, `package`, `evaluate` — the catalog chip and hook-target family. |
| `capabilities` | ✓ | Non-empty list of `{ id, contractVersion }` — the semantic contracts this agent implements (see §3). |
| `provenance` | ✓ | `{ publisher, license?, trust? }`; `trust` is one of `built-in`, `global`, `imported`. |
| `purpose`, `roles` | | One-line description and display roles. |
| `delegatesTo` | | Other `agent.` ids this agent may call. Expresses a preferred implementation only — it grants nothing and never auto-imports or auto-installs. |
| `prompts` | | Prompt assets by **contained** package-relative `path` + `sha256` + declared `variables`. Absolute paths and `..` escapes are rejected. |
| `compatibleTargets` | | Where the agent can attach: `{ kind: node\|canvas\|connection, requires: [...] }`. |
| `inputs`, `outputs` | | Context the agent reads / config it requires / named outputs it produces. |
| `runtime` | | `execution` (`foreground`\|`background`) and `reviewPolicy` (`report-only`\|`review-before-apply`). |
| `providerRequirements` | | Provider *capability* requirements (e.g. `structured-output`). Provider **credentials** are selected through an authorized account-level provider profile outside the manifest. |
| `tools` | | Typed, allowlisted tool **requirements** — never executable code or permission grants. |
| `settingsDefaults` | | Immutable, non-secret seed suggestions plus a reviewed profile-family id/version. A manifest cannot create a new trusted profile family implicitly. |

The on-disk directory name is authoritative: the loader cross-checks it against the manifest's `id` and `version` and rejects a mismatch, exactly as the node-package loader does.

---

## 3. Capabilities

A **capability** is a semantic behavior contract — *what* an agent does — kept deliberately separate from the prompt file that implements it. A capability id is two or more dot-separated lowercase segments:

```
node.explain            dataflow.orchestrate       package.recommend
node.output.interpret   dataset.fetch.author       connection.propose
```

Capability ids are used for catalog discovery, orchestration resolution, compatibility, and substitution — **never for authorization**. Because they are contracts and not assets, a capability id **must not** contain a prompt filename, path separator, underscore, or `.txt`. So `node.explain` is valid; `single_box_explanation_prompt` or `prompts/explain.txt` are rejected. This keeps the "what" (capability) cleanly independent of the "how" (prompt asset), so a prompt can be edited or replaced without changing the capability contract.

`delegatesTo` lets one agent compose over another's capabilities (an orchestrator delegating to specialists, for example). Delegation names a preferred implementation; it never grants permission and never triggers an import or install on its own.

---

## 4. The default LLM provider

An agent's `providerRequirements` declare what it needs from a provider (e.g. `structured-output`); the *actual* provider, model, endpoint, and key come from configuration, not the manifest. Curio resolves this from a **single default** so there is no separate built-in default scattered through the code: when a user has not configured their own provider under **LLM Settings**, the app falls back to `config.DEFAULT_LLM_*`, seeded from the sage200 OpenAI-compatible endpoint.

| Setting | Env var | Default |
|---|---|---|
| Provider type | `CURIO_DEFAULT_LLM_API_TYPE` | `openai_compatible` |
| Base URL | `CURIO_DEFAULT_LLM_BASE_URL` | `https://sage200.evl.uic.edu/v1` |
| Model | `CURIO_DEFAULT_LLM_MODEL` | `llama4-nim` |
| API key | `CURIO_DEFAULT_LLM_API_KEY` / `AICONN_API_KEY` | *(unset)* |

Resolution rules (`_resolve_llm_config` in [`app/api/routes.py`](../utk_curio/backend/app/api/routes.py)):

- A user who has configured their own provider under **LLM Settings** keeps that exact config — the default never overrides or contaminates it (a configured Anthropic user never picks up the default base URL).
- An **unconfigured** user falls back to the default provider above rather than being turned away.
- **Guests** use `GUEST_LLM_*`, which inherits `DEFAULT_LLM_*` unless separately overridden, so guests default to the same provider.

Operators point the whole install at a different default by setting the env vars above; individual users still override per-account under LLM Settings. The API key is read from `AICONN_API_KEY` (the same name used by the connection harness) when a dedicated `CURIO_DEFAULT_LLM_API_KEY` is not set.

---

## Appendix: validating a manifest (developer-only)

The canonical spec is [`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json). The backend validator that implements the supported subset lives in [`utk_curio/backend/app/agents/manifest.py`](../utk_curio/backend/app/agents/manifest.py) and mirrors the node-package validator ([`app/packages/manifest.py`](../utk_curio/backend/app/packages/manifest.py)):

```python
from pathlib import Path
from utk_curio.backend.app.agents.manifest import load_agent_manifest, parse_agent_manifest

manifest = load_agent_manifest(Path("agents/agent.node-explainer@1.0.0"))
# or validate an already-parsed dict:
manifest = parse_agent_manifest(raw_dict)
```

Both raise `AgentManifestError` (a `ValueError`) with a `{where}.field` message pointing at the offending field. The validator enforces the id/version grammar, the capability-id rules above, prompt-path containment, and the directory/manifest agreement.

---

## See also

- [`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json) — the manifest JSON Schema.
- [`docs/CATALOG.md`](CATALOG.md) — the Node Catalog, whose package/catalog model hookable agents mirror.
- [`utk_curio/backend/app/agents/manifest.py`](../utk_curio/backend/app/agents/manifest.py) — the manifest validator.
