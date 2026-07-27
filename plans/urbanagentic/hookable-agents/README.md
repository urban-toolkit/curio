# Hookable Agents Planning Package

This directory contains the current implementation plan and approved UI direction for hookable agents in Curio. It is a planning package; application implementation has not yet been performed.

## Current Product Direction

```text
immutable manifest definition
  -> explicit private account Import
  -> explicit selected-project Install
  -> private project/user-scoped attachment
  -> governed execution and review
  -> optional reuse of Curio's existing flow-sharing (no agent-private data exposed)
```

- Import, Install, Attach, and Publish are independent explicit actions (there is no agent Share command — agents reuse Curio's existing flow-sharing, D-0 = B).
- Only an owned, validated, manifest-based account import is currently user-publishable. **Publish lists the owned definition in the global Catalog Hub from the My Imports scope, using the same `Publish` → `Published` control as datasets and node packs**, so other users can discover and install it.
- A project installation creates a `ProjectAgentTemplate` with independent project defaults; it is not publishable.
- An `AttachedAgentInstance` is a private configured derivation with an `attachmentId` and concurrency `revision`, not a versioned/shareable package.
- Agents reuse Curio's existing flow-sharing; the feature adds no agent-private data (the source project or its datasets, packages, agents, settings, prompts, history, providers, tools, IDs, or execution state) as a new shared surface.
- Node explanation runs through the built-in node Explanation tab (retained permanently — `DEC-041`, `dev/18`) and, additionally, through a project-installed, node-attached Node Explainer unified chat. The former plan to remove the tab is cancelled and must not be reintroduced.
- All agent/LLM UI and behavior belongs under frontend and backend `agents/` modules behind typed public interfaces.
- Agent package IDs use the `agent.` prefix. Semantic capabilities describe behavior; prompt filenames remain package assets and are never capability IDs.

## Canonical Reading Order

1. [`dev/00-development-phase-index.md`](dev/00-development-phase-index.md) — development-phase entry point and authoritative reading order.
2. [`dev/03-agents-catalog-development-plan.md`](dev/03-agents-catalog-development-plan.md) — decisions, requirements, risks, open questions, phases, and acceptance criteria.
3. [`dev/05-agents-catalog-implementation-blueprint.md`](dev/05-agents-catalog-implementation-blueprint.md) — module structure, contracts, data flows, persistence, APIs, tests, and incremental implementation plan.
4. [`dev/11-agent-configuration-modals-and-prompt-governance-memo.md`](dev/11-agent-configuration-modals-and-prompt-governance-memo.md) — six scope-aware settings screens and per-project-template defaults.
5. [`dev/12-agent-template-installation-attachment-sharing-lifecycle-memo.md`](dev/12-agent-template-installation-attachment-sharing-lifecycle-memo.md) — definitive lifecycle, sharing, and Node Explainer decisions.
6. [`dev/13-agent-documentation-consolidation-and-obsolete-plan-removal-memo.md`](dev/13-agent-documentation-consolidation-and-obsolete-plan-removal-memo.md) — canonical-source and obsolete-document removal policy.
7. [`dev/kggraph/Stage-2-Design-Phase/2.1-Agents-Catalog-Design-Traceability.md`](dev/kggraph/Stage-2-Design-Phase/2.1-Agents-Catalog-Design-Traceability.md) and [`dev/kggraph/Stage-3-Build-Phase/3.1-Agents-Catalog-Build-Log.md`](dev/kggraph/Stage-3-Build-Phase/3.1-Agents-Catalog-Build-Log.md) — requirement/evidence traceability.

The numbered product specifications under `docs/01-...` through `docs/11-...` provide the current product, UI, interaction, runtime, prompt, and manifest detail. Two supporting UI memos remain because they define current unique visual behavior:

- [`docs/00-attached-agent-dock-memo.md`](docs/00-attached-agent-dock-memo.md)
- [`docs/00-chat-feedback-visual-identity-memo.md`](docs/00-chat-feedback-visual-identity-memo.md)

## Current Application Evidence

The existing application still contains legacy paths that the plan migrates rather than treats as target behavior:

- direct `llmRequest(...)` calls in general frontend components;
- prompt files in `utk_curio/llm-prompts/` rather than manifest packages;
- a project-ID public share route that hydrates the project into a shared-guest workspace and can expose a Save-a-copy flow.

(The node Explanation tab and its direct `single_box_explanation_prompt` caller were formerly in this migrate-then-remove list; per `DEC-041` (`dev/18`) they are **retained target behavior**, not a legacy path.)

The plan requires parity and regression coverage before removing those paths. Thirteen requested prompt assets currently exist. `evaluate_generated_content_prompt.txt` and a current caller do not; the corresponding agent remains disabled under `OQ-007` until authoritative content and contracts are supplied.

## UI and Generated Artifacts

- `docs/01-consolidated-plan.md` through `docs/11-agent-manifest-and-product-model.md`: canonical product and technical specifications.
- `png-concepts/` and `svg-concepts/`: generated concept screens.
- `figma-ready/`: vector handoff metadata and tokens.
- `Agentic-Functionality-Workbook.xlsx` and `workbook-assets/`: earlier walkthrough artifacts.
- `sources/render_hookable_agents_png_concepts.py`: deterministic PNG/SVG renderer.
- `sources/build_functionality_workbook.py`: deterministic workbook builder.
- `png-ideas/`: visual references from the current Curio UI.

The generated screens and workbook now reflect the finalized model: the three-scope lifecycle drawer (Global Catalog / My Imports / Installed in this project), the six governed settings screens, the settings scope-applicability matrix, the reviewed `Install in project` orchestration (no auto-install), and the `DEC-042` header split (agent identity + cycling + Close in the opened agent view's single top header, no Pin there; the static `Agents Catalog` header is roster-drawer-exclusive with the Pin only). (Generated screens that depict the node Explanation tab as removed are stale on that point: per `DEC-041` (`dev/18`) the tab is retained and coexists with Node Explainer chat.) Agents rely on the system's **existing** sharing behavior described in the specs — there is no dedicated agent-sharing screen or flow. Where visual details and text specifications differ, the specifications remain authoritative.

## Supporting Visual Decisions

- Curio chrome, typography, icons, and layout are summarized in [`docs/03-ui-decisions.md`](docs/03-ui-decisions.md), [`docs/05-png-concepts.md`](docs/05-png-concepts.md), and [`docs/07-icon-source-map.md`](docs/07-icon-source-map.md).
- Unified chat behavior and visual feedback are defined in [`docs/08-unified-agent-chat.md`](docs/08-unified-agent-chat.md).
- Attached agents use accessible icon-only dock tiles with tooltips, state indicators, keyboard parity, and reduced-motion behavior.
- Settings use clear cog buttons and one accessible modal shell with dedicated Cost, Quotas, Resource policies, Prompt quality, Prompt editor, and Prompt audit screens.
