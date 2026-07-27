# Implementation Memo: Agent Documentation Consolidation and Obsolete Plan Removal

## 1. Problem Statement

The Agents planning set contains several generations of lifecycle, catalog, attachment, sharing, explanation, prompt, and UI proposals. Some early memos still describe account-wide installation, automatic installation, attached-agent publication or versioning, live shared projects, and catalog actions that are no longer part of the approved plan. (Historical note: this list originally included "a built-in node Explanation tab" as obsolete; `DEC-041` (`dev/18`) later reversed that — the tab is current, approved behavior, and documents instructing its *removal* are the obsolete ones.) Supersession notices reduce—but do not remove—the risk that a developer, reviewer, or automated planning tool will implement an obsolete path.

The documentation must become a single coherent implementation source that matches the current plan and the application surfaces being changed. The retained plan must consistently describe reusable manifest-based definitions, explicit account Import, explicit project Install, private project/user-scoped attachment, imported-definition-only publication, reuse of Curio's existing flow-sharing (no new sharing mechanic — D-0 = B), Node Explainer chat, semantic capabilities, `agent.` package identifiers, and scope-correct settings and prompt governance.

## 2. Scope

Included:

- all Agents planning Markdown under `plans/urbanagentic/hookable-agents/dev/` and `plans/urbanagentic/hookable-agents/docs/`;
- the Agents development index, organization memo, README, active decision register, requirements, risks, open questions, KGGraph design traceability, and build log;
- references from retained planning documents and generated-artifact README files;
- comparison with the current application code paths for node explanation, prompts, dataflow sharing, datasets, packages, and project-scoped state;
- migration of still-valid implementation or UI guidance from a redundant memo before that memo is deleted;
- deletion of planning documents whose core model conflicts with, duplicates, or has been fully absorbed by the canonical plan.

Out of scope:

- application implementation, generated PNG/SVG regeneration, workbook regeneration, or source-code deletion;
- deletion of the separate reference knowledge-graph project under `knowledge-graph/`;
- reopening approved product decisions solely because an older memo proposed a different behavior.

## 3. Recommended Implementation Approach

Use a canonical-source policy instead of preserving every planning generation:

1. Treat the root README and numbered development documents as the implementation entry point.
2. Retain the numbered product and architecture specifications only when they express the current model and add unique implementation detail.
3. Retain a supporting `00-...-memo.md` only when its complete purpose remains current and it contains unique, actionable UI or visual guidance that is not represented elsewhere.
4. Migrate valid unique guidance into a canonical document before deleting a redundant or conflicting source.
5. Delete documents whose central lifecycle, ownership, UI, sharing, or state assumptions are obsolete. A supersession banner is not sufficient for a document that could still be mistaken for implementation direction.
6. Remove obsolete decision and requirement rows from active tables. Do not reuse retired identifiers; gaps communicate retirement without keeping conflicting instructions active.
7. Rewrite KGGraph evidence so every active requirement and decision points only to retained, current sources.
8. Repair all relative links and update the recommended reading order after pruning.

The minimum canonical set is:

- `README.md`;
- `dev/00` through the latest numbered memo (this consolidation memo and the later amendments `dev/14` plan-hardening, `dev/15` composite-agent specs, and `dev/16` node-package capabilities), after their active tables and language are reconciled;
- `dev/kggraph/Stage-2-Design-Phase/2.1-Agents-Catalog-Design-Traceability.md`;
- `dev/kggraph/Stage-3-Build-Phase/3.1-Agents-Catalog-Build-Log.md`;
- `docs/01-consolidated-plan.md` through `docs/11-agent-manifest-and-product-model.md` when each remains current;
- only the supporting UI/visual memos that pass the keep criteria above.

Consolidation result:

- Retained supporting memos: `docs/00-attached-agent-dock-memo.md` and `docs/00-chat-feedback-visual-identity-memo.md`, because their complete purpose remains current and their detailed dock/feedback visual guidance is unique.
- Removed lifecycle/product/workflow memos after their current guidance was absorbed by the numbered specifications: the former catalog roster, product model, catalog-versus-palette, install/publish parity, Dataflow Builder orchestration, Dataset Finder workflow/source suggestions, unified-chat refinement, workbook, and initial design-package implementation memos.
- Removed visual-generation history memos after their current renderer/icon/typography guidance was consolidated into `docs/03-ui-decisions.md`, `docs/05-png-concepts.md`, `docs/07-icon-source-map.md`, and the artifact README files: the former PNG implementation, Curio redraw, dataset dropdown, render-quality/top-bar, icon consistency/replacement, and Figma export memos.
- Renamed development memo `09` to `09-agent-import-project-installation-and-privacy-memo.md` so its filename no longer implies an account-wide installation model.
- Retired decision and requirement IDs remain unused; obsolete text is not retained in active tables or KGGraph matrices.

### Filename-level delete / retain (execute the policy by filename, never by description)

The prose removal list above names memos *descriptively*; to execute it safely, treat removal and
retention as filename operations:

- **Removed (by filename):** the former `docs/00-*`-prefixed workflow and visual-history memos
  (e.g. `00-dataflow-builder-orchestration-memo.md`, `00-dataset-finder-workflow-replan-memo.md`,
  `00-dataset-finder-source-suggestions-memo.md`, `00-unified-agent-chat-refinement-memo.md`,
  `00-agents-*-memo.md`, and the PNG/redraw/dataset-dropdown/render-quality/icon/Figma memos).
- **Retained (by filename):** the numbered specifications `docs/01-…` through
  `docs/11-…` — including `docs/06-dataset-finder-source-review.md`, `docs/08-unified-agent-chat.md`,
  `docs/09-agent-architecture.md`, and `docs/10-prompt-architecture.md`, which are **different
  files** from the removed workflow memos and are still cited by `docs/03`, `docs/11`, and
  `dev/03` (DEC-005/DEC-007) — plus `docs/00-attached-agent-dock-memo.md`,
  `docs/00-chat-feedback-visual-identity-memo.md`, the `dev/` package, and the KGGraph artifacts.
- **Invariant:** only two `docs/00-*` memos remain (dock + chat-feedback). The descriptive removal
  wording must never be read as authorizing deletion of a numbered `docs/NN-…` spec.

## 4. Data and State Handling

Documentation must use one lifecycle and one source-of-truth model:

```text
AgentDefinitionArtifact
  -> explicit AccountImportedAgent
  -> explicit ProjectAgentTemplate
  -> explicit AttachedAgentInstance
  -> governed execution
```

- An import is an account-private reusable manifest package and does not install or publish automatically.
- A project installation is a project-scoped template with independent default settings and is not directly publishable.
- An attachment is a private configured derivation scoped to a project and target, uses an `attachmentId` plus concurrency `revision`, and has no publication, sharing, release, or SemVer lifecycle.
- Only an owned, validated imported manifest definition is user-publishable for the current phase.
- Sharing is out of scope (D-0 = B): agents reuse Curio's existing flow-sharing and add no new sharing mechanic; agent-private data (definitions, imports, templates, attachments, agent flows, settings, prompts, governance, transcripts, private IDs) is not added as a new shared surface.
- Prompt authoring, quality evaluation, security/compliance audit, and audit history belong to authorized account imports. Project templates and attachments expose only permitted read-only provenance, with downward-only runtime policy overrides.
- State descriptions must be keyed by account, project, template, attachment, or execution identity as appropriate; the plan must not revive an account installation singleton or infer a project from a dataflow identifier.
- Identifier convention: standardize one project/dataflow key across the data model and API. The current repo keys a dataflow by `dataflow_id`; if the target model treats project and dataflow as one entity, use `dataflowId` everywhere, and if a distinct multi-dataflow `projectId` is intended, define it explicitly and map the two. `projectId` and `dataflowId` must never be used interchangeably for the same key (reconcile the mixed usage in blueprint `05` data model, `SettingsScope`, and routes).

## 5. UI and UX Requirements

Retained documentation must consistently specify:

- clear drawer separation among Global Catalog, My Imports, and Installed in this project;
- separate Import, Install, Attach, and Publish actions with no hidden chaining (sharing reuses existing flow-sharing — no agent Share command);
- project palette entries as project templates, with settings and uninstall reached from the appropriate drawer detail rather than row-level action clutter;
- a private attached-agent dock and unified chat; no publish/share/release/version controls on attachments;
- six dedicated settings modal screens reached through clear cog/settings affordances: Cost, Quotas, Resource policies, Prompt quality, Prompt editor, and Prompt audit;
- scope-aware editability: Cost/Quota/Resource defaults at the project-template level, downward-only attachment overrides, and Prompt screens editable only for authorized imported definitions;
- Node Explainer Agent chat as a node-explanation surface **coexisting with the retained built-in node Explanation tab** (`DEC-041`, `dev/18` — the former sole-path/removal model is superseded);
- no agent sharing UI (D-0 = B): agents reuse Curio's existing flow-sharing, and agent-private data is not exposed in the existing public result view.

All retained UI guidance must preserve the approved visual language, keyboard access, focus management, semantic labels, safe rendering, zoom/reflow, reduced motion, and WCAG 2.2 AA expectations.

## 6. Edge Cases

- A deleted memo is still linked from a canonical plan, KGGraph row, generated-artifact README, or source register.
- A supporting memo mixes valuable current visual guidance with an obsolete lifecycle assumption; the valid material must be migrated before deletion.
- A retired decision identifier is referenced by an active requirement or test even after its decision row is removed.
- Two retained documents use the same term for different entities, such as “installed agent” for both an account import and a project template.
- Stale text permits publication from a built-in/global definition, installed project template, attachment, or implicit private fork.
- Stale sharing text exposes project IDs, live resource access, shared-guest workspaces, project cloning, or private dependencies.
- Stale node guidance instructs removing the Explanation tab, cache, or provider call (`DEC-041` reversed this: retaining them is current direction; a document instructing removal is the stale one).
- Generated concepts still depict an older flow; their README must identify them as non-canonical and pending regeneration rather than allowing imagery to override current text.
- A relative Markdown link contains anchors, spaces, or nested paths that a simple existence check could mis-handle.

## 7. Testing Strategy

The documentation change is complete only after automated and manual validation:

- run a relative Markdown link checker across all retained Agents Markdown;
- verify balanced fenced code blocks and Mermaid fences;
- search retained active documents for obsolete terms and routes, including account installation, automatic install, attached publication/versioning, shared guest/editor, the legacy project-ID share route, and any instruction to remove the node Explanation tab (obsolete under `DEC-041` — the tab is retained);
- search for every deleted filename and fail if a retained document still references it;
- validate active decision and requirement identifiers for duplicate definitions, missing definitions, and references to retired entries;
- verify the KGGraph source register, traceability matrix, and build log point only to retained canonical sources;
- compare the Node Explanation migration references and prompt inventory against the actual repository paths;
- manually review the retained reading order, scope/editability matrices, lifecycle diagrams, and shared-output exclusion list for semantic consistency.

## 8. Acceptance Criteria

- The root README identifies one current reading order and no deleted source.
- Every retained planning document is consistent with explicit Import, project Install, private Attach, imported-only Publish, and reuse of existing flow-sharing (no new agent sharing mechanic — D-0 = B).
- No active document describes account-wide installed agents, project/dataflow-derived publication scope, automatic installation, versioned/shareable attachments, live shared projects, or removal of the built-in node Explanation tab (retained per `DEC-041`).
- Obsolete and fully redundant Agents planning memos are deleted after their valid unique guidance is preserved where needed.
- Active decision, requirement, risk, and open-question tables contain only current implementation direction; retired IDs are not reused.
- KGGraph design and build documents trace only current requirements to retained sources and implementation evidence.
- Prompt files remain package resources rather than semantic capabilities; manifests use semantic capabilities and the `agent.` package prefix.
- Settings and prompt-governance documentation uses the approved six screens, correct ownership scopes, per-project-template defaults, and clean provider interfaces.
- Shared-output documentation states agents reuse Curio's existing flow-sharing and add no new sharing mechanic; agent-private resources and configuration are not exposed in the existing shared result.
- All retained relative links resolve, all fences balance, and no deleted filename remains referenced.

## 9. Recommended Commit Breakdown

1. Add this consolidation policy and inventory the canonical set.
2. Migrate unique current guidance from redundant historical memos into canonical specifications.
3. Delete obsolete/conflicting memos and remove their source-register and decision references.
4. Reconcile development indexes, active decision/requirement tables, KGGraph traceability, and build evidence.
5. Repair links and artifact notices, then add documentation consistency validation results.

## 10. Engineering Quality Checklist

- [ ] The retained set has a clear source-of-truth hierarchy.
- [ ] No conflicting lifecycle or sharing model remains actionable.
- [ ] Valid unique guidance was preserved before its source was removed.
- [ ] Active decisions and requirements are current, singular, and traceable.
- [ ] Entity names and ownership scopes are used consistently.
- [ ] UI actions and settings editability match the approved concepts.
- [ ] Current app migration points are cited accurately.
- [ ] Relative links and code fences pass validation.
- [ ] Generated artifacts are clearly marked when they lag the text plan.
- [ ] No application code or unrelated knowledge-graph content was changed.
