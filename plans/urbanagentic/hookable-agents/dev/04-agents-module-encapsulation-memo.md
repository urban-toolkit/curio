# Implementation Memo: Frontend and Backend `agents/` Encapsulation

## 1. Problem Statement

Existing LLM behavior is spread across general frontend providers/components and broad backend routes, including a bespoke node Explanation tab/direct caller (which is retained permanently per `DEC-041`, `dev/18`, as a grandfathered exemption outside the `agents/` boundary). Without an explicit boundary, the revised definition/import/project-template/private-instance lifecycle, runtime, settings, prompt governance, and output sanitization could remain scattered across dataset, node, flow, and generic UI modules. New agent/LLM behavior must be owned by `agents/` on both sides while reusable primitives remain shared.

## 2. Scope

Included: module ownership for immutable definitions, private account imports, imported-only publication, project templates/palettes/defaults, private attachments, runtime/providers/tools/prompts, settings/usage, prompt quality/compliance audit/governance, Node Explainer migration, tests, and source moves. Out of scope: physically moving implementation files in this planning pass or moving feature-neutral HTTP, dialog, form, editor, schema, renderer, and snapshot primitives merely because agents use them.

## 3. Recommended Implementation Approach

Create one narrow public `agents/` module per application layer. Frontend `src/agents/` owns Global Catalog/My Imports/Installed-in-project read models, the active-project palette, dock/chat/attachment UI, Node Explainer discoverability, settings screens, and prompt editor/evaluation/audit state. Backend `app/agents/` owns lifecycle policies/services/repositories, imported-definition-only publication authorization, project defaults, runtime/providers, reservations/usage, and prompt governance.

Non-agent features use documented public ports. Dataset/node/flow code may expose typed context/tools or visible presentation inputs, but it cannot import agent internals, construct LLM requests, decide lifecycle/policy, load prompts, or expose private agent state.

## 4. Data and State Handling

Definition artifacts, account imports, publications, project templates/settings, private attached instances, sessions/executions, provider/runtime state, settings/effective snapshots/reservations, and prompt governance flow through agent hooks/selectors and application services. The project palette is keyed by `projectId`, not an account installation pointer. Attachment `revision` is concurrency state, not artifact versioning. Prompt bodies use owner-authorized imported-definition endpoints and memory-only editor state.

Project switching clears/replaces template, palette, attachment, settings, chat, and stream state. Account switching additionally clears imports, prompt drafts, evaluation/audit state, and provider-scoped state. Prompt bodies and private lifecycle data never enter shared caches, URLs, logs, telemetry, or generic catalog DTOs.

## 5. UI and UX Requirements

Agent catalog/import/project palette, dock/chat, private attachment, execution status, settings launchers/screens, prompt governance, and Node Explainer flow belong under frontend `agents/`. Cost/Quota/Resource settings apply to account policy, project-template defaults, and downward-only instance overrides; Prompt Editor/Quality/Audit authoring applies only to owned definitions created through explicit account Import. Built-in/global definitions, project templates, and instances may inspect authorized source evidence read-only and expose no Release/Publish/version action. Any future fork/export must be packaged and explicitly re-imported and is out of scope.

Remove the node Explanation component/tab/state/cache/direct caller instead of retaining it as shared node UI. Node Explainer unified chat is the only explanation surface. Generic accessible dialog/form/editor and safe visible-content rendering primitives remain shared.

## 6. Edge Cases

- Avoid circular dependency between agents and flow/node/dataset modules.
- Preserve a legacy LLM caller only behind a time-bounded compatibility adapter until migration parity; remove it at cutover.
- Do not expose an account-wide installed store/palette or let project state leak across project switches.
- Do not let clients Publish from built-ins/global entries/project templates/instances or auto-chain Import/Install/Publish.
- Do not add SemVer, release, or publication identity to `AttachedAgentInstance`.
- Remove every Explanation-tab import, cache, loading/error state, test fixture, and raw prompt/provider path after parity.
- Purge prompt bodies and private modal/stream state on close, project/account switch, and authorization loss.

## 7. Testing Strategy

Add import-boundary, lifecycle, provider/runtime/policy, prompt-governance, component, and regression tests. Verify no raw LLM/explanation call, LangChain/provider import, lifecycle/policy resolution, prompt-content access, or evaluation/audit mutation exists outside approved agent infrastructure. Prove project/account cache isolation, imported-only Publish, explicit command separation, project palette/default ownership, and attachment revision without versioning. Prove Node Explainer chat executes once; the Explanation tab/direct caller is retained outside the `agents/` boundary (`DEC-041`, `dev/18`) and is exempt from the no-raw-LLM-call boundary checks.

## 8. Acceptance Criteria

- Frontend and backend agent responsibilities are contained under their `agents/` modules and exposed through narrow public ports.
- Definition, account import, project template, private instance, and publication are distinct contracts.
- Only owned validated imports can use user Publish; Import/Install/Attach/Publish never auto-chain.
- Project palettes/defaults are project-keyed; no account-wide installed pointer remains.
- Instances expose only attachment identity/concurrency revision and no version/release/publish contract.
- Node UI keeps its existing Explanation tab/cache/direct path unchanged (`DEC-041` — a grandfathered exemption to the `agents/` boundary); Node Explainer chat coexists through the standard agent workflow.
- Settings and prompt governance remain agent-owned at memo-12 scopes; generic primitives remain feature-neutral.

## 9. Recommended Commit Breakdown

1. Establish public APIs and import-boundary tests.
2. Move backend providers/prompts/runtime and lifecycle services into `app/agents/`.
3. Add account-import/imported-only-publication and project-template/instance ports.
4. Add project policy/reservations and imported-definition prompt-governance ports.
5. Move frontend lifecycle, project palette, chat, settings, and prompt governance under `src/agents/`.
6. Remove Explanation and obsolete account-install paths; update imports/tests/docs and run regressions.

## 10. Engineering Quality Checklist

- [ ] Agent ownership and public boundaries are explicit and acyclic.
- [ ] No provider/LangChain/raw prompt/explanation behavior leaks into node/flow/dataset UI.
- [ ] No lifecycle/session/settings/prompt state is duplicated in non-agent stores.
- [ ] Project palettes/defaults are project-isolated; account imports remain separate.
- [ ] Publish eligibility and explicit lifecycle commands are server-authoritative.
- [ ] Attached instances are unversioned private derivations.
- [ ] Prompt editor state is memory-only and principal/project safe.
- [ ] Shared primitives remain reusable and feature-neutral.
- [ ] Tests/docs use final paths and remove obsolete Explanation/account-install contracts.
