# Implementation Memo: Agent Import, Project Installation, and Privacy

**Role.** This is the active **privacy companion** to the lifecycle memo, not a superseded document. `12-agent-template-installation-attachment-sharing-lifecycle-memo.md` is authoritative for the import/install/attach/publish lifecycle; this memo owns the account/project isolation and privacy invariants for that lifecycle and defers to `12` on any lifecycle mechanics. It uses the current lifecycle defined by `12` and active decisions `DEC-029` through `DEC-033`, and the sharing scope of `14-plan-hardening-and-open-decisions-memo.md` (D-0 = B).

## 1. Problem Statement

The former plan installed an agent once at account scope and exposed it in every dataflow. That model conflated account-private reusable definitions, project installation, attached runtime instances, and publication. The revised model requires an explicit private account import, an explicit project-only template installation, and a private attached instance. Node explanation is served by the retained built-in Explanation tab and, additionally, by the attached Node Explainer chat (`DEC-041`, `dev/18` — the former removal is cancelled).

## 2. Scope

Included: immutable definition artifacts; explicit `AccountImportedAgent` creation; imported-definition-only user publication; explicit `ProjectAgentTemplate` installation/uninstallation; project-only palettes and per-project defaults; private `AttachedAgentInstance` identity/configuration/history; prompt authoring/evaluation/compliance-audit scope; account/project cache isolation; Node Explainer migration; APIs; persistence; tests; and traceability. Out of scope: automatic import/install/publish, account-wide installed palettes, publishing or sharing project templates/attachments, attachment SemVer, live/editable shared projects, cross-account execution, project-private prompt overrides, and final retention periods outside `OQ-008`.

## 3. Recommended Implementation Approach

Use these separate aggregates and explicit commands:

```text
AgentDefinitionArtifact (immutable manifest package)
  ├─ explicit Import ──> AccountImportedAgent (account-private, publish eligible when owned/validated)
  │                         ├─ explicit Publish ──> Global Agents Catalog
  │                         └─ explicit Install(projectId)
  └─ built-in/global visible definition ── explicit Install(projectId)
                                            ▼
                                  ProjectAgentTemplate
                                  (one project and its palette/defaults)
                                            │ explicit Attach(target)
                                            ▼
                                  AttachedAgentInstance
                                  (private; attachmentId + concurrency revision)
```

Import validates a manifest package in bounded private staging and creates an immutable artifact plus an account-private ownership/provenance record. It never changes a project, installs, or publishes. Install selects one authorized project and creates a `ProjectAgentTemplate` plus independent project defaults; it never publishes. User Publish accepts only an owned validated `AccountImportedAgent`; built-ins, global catalog entries, project templates, and attachments cannot enter that command. System-curated catalog ingestion is a separate administrative path.

`AttachedAgentInstance` references a `projectAgentTemplateId` and target. Its `revision` exists only for optimistic concurrency; it has no SemVer, artifact coordinate, release, or publication lifecycle. Execution reproducibility pins the resolved source definition digest, project-settings revision, attachment revision, prompt digest, provider-profile revision, and effective-policy snapshot.

## 4. Data and State Handling

- `AgentDefinitionArtifactRepository` owns immutable exact package bytes.
- `AccountImportedAgentRepository` owns account-private import/provenance/validation/publication eligibility.
- `AgentPublicationRepository` owns global catalog entries that reference eligible imported artifacts; publication never installs.
- `ProjectAgentTemplateRepository` owns project installation and is the sole source of the active project's AGENTS palette.
- `ProjectAgentSettingsRepository` owns typed per-template Cost, Quota, and Resource policy revisions seeded at explicit install.
- `AttachedAgentInstanceRepository` owns project-private target bindings, concurrency revision, session reference, and downward-only overrides.
- Session/execution/event/usage stores remain private and pin reproducibility inputs without versioning the attachment.
- Prompt authoring workspaces, draft revisions, evaluation suites/runs, compliance-audit policies/runs/findings, reviewer decisions, releases, and governance events belong only to an owned `AccountImportedAgent` created through explicit Import. Built-in/global definitions, project templates, and attachments may inspect authorized source evidence read-only but cannot edit, release, or publish it. Any future fork/export must be packaged and explicitly re-imported and is out of scope.

The effective runtime policy is the strictest deployment ceiling ∩ account safety/privacy policy ∩ project-template default ∩ attached-instance downward-only override ∩ atomic reservation. Reset restores the selected project's template default, never another project or the imported definition. Project switching replaces palette/settings/attachment/session caches; account switching additionally purges imports, prompt editor state, evaluation/audit streams, and all private caches.

## 5. UI and UX Requirements

- The Agents drawer clearly separates `Global Catalog`, `My Imports`, and `Installed in this project`.
- `Import package` ends at a private imported-definition detail. `Install in project` and eligible `Publish` are distinct explicit actions; neither chains to the other.
- Global/built-in cards offer `Install in project`; project templates/palette rows show project installation state/settings/uninstall and never Publish.
- The AGENTS palette lists only `ProjectAgentTemplate` records for the active project. Project switching announces and replaces its contents without carrying templates or instances across projects.
- Settings scope labels are `Account policy`, `Imported definition`, `Project agent default`, and `Attached instance`. Cost/Quota/Resource screens edit account bounds, project defaults, or downward-only instance overrides as applicable. Prompt Editor/Quality/Audit edit or run only for an owned imported definition; project templates/instances show authorized provenance/evidence read-only and never Release/Publish.
- Attached UI shows project template, target, private scope, status, chat, and settings. It shows no Version, Release, Publish, or catalog identity.
- Keep the node `Explanation` tab/menu/keyboard target/loading/error/cache and direct raw prompt/provider call unchanged (`DEC-041` — the removal is cancelled). `Explain with Node Explainer` may additionally open the normal project install → attach → unified chat flow.

## 6. Edge Cases

- Import completes with no project open, is repeated, or collides on publisher/ID/version/digest; no project changes and idempotency/collision policy applies.
- Install is repeated for one project, or the same definition is installed in two projects with different defaults; each project remains isolated.
- Publish is fabricated for a built-in/global item, project template, attachment, or invalid/unowned import; the server rejects it without enumerating private state.
- An imported artifact is unpublished/deleted while project templates or retained execution pins reference its bytes; retention/reference rules preserve required bytes or block deletion.
- Project uninstall races with attach or active reviews/executions; the same-project lock yields one stable result and never detaches silently.
- Two tabs edit one attachment; optimistic revision conflict does not create an attachment version.
- Node Explainer is absent, over quota, provider-blocked, or fails; use the normal project install/attach/chat recovery path (the retained Explanation tab continues to work independently — `DEC-041`).
- Legacy saved Explanation-tab state is ignored/removed without deleting valid project content.

## 7. Testing Strategy

Add domain/contract tests for legal definition/import/project-template/attachment transitions and explicit command separation. Prove imports are account-private, bounded, idempotent, and cause no project or publication mutation. Prove only owned validated imports can use user Publish. Prove project install materializes independent defaults and only the selected project palette updates. Prove attachments use `attachmentId` plus concurrency revision only, expose no publish/version APIs, and executions pin reproducibility inputs.

Add project/account-switch cache cleanup, snapshot consistency, and authorization tests. Add Node UI tests proving the retained Explanation tab still renders and works (`DEC-041`) and that Node Explainer uses the standard explicit install/attach/chat workflow with no double call.

## 8. Acceptance Criteria

- Explicit Import creates one private `AccountImportedAgent` and never installs or publishes it.
- Only an owned validated imported manifest definition can enter user Publish; Publish and Install are independent.
- Explicit Install creates a `ProjectAgentTemplate`, project-only palette membership, and isolated project defaults.
- `AttachedAgentInstance` is project/user-private, identified by `attachmentId`, concurrency-revisioned only, and has no SemVer/release/publish lifecycle.
- Project templates and attachments have no Publish UI, route, capability, or authorization.
- Cost/quota/resource defaults are per project template; instance overrides only tighten account/deployment constraints.
- Prompt edit/evaluate/compliance-audit/release applies to owned imported definitions, not templates/instances; evidence inspection at lower scopes is read-only.
- Node Explainer unified chat is a coexisting node-explanation workflow; the Explanation tab and direct caller are retained (`DEC-041`).
- All boundaries are enforced server-side, non-enumerating, cache-isolated, and traceable.

## 9. Recommended Commit Breakdown

1. Add lifecycle aggregates, commands, filesystem stores/registries/lockfile, and legal-transition tests.
2. Add bounded private account import and imported-only publication authorization.
3. Add explicit project template install/uninstall, project palette, and isolated defaults.
4. Add private unversioned attachments and reproducibility snapshots.
5. Remove node Explanation UI/direct call and migrate to Node Explainer chat.
6. Align settings/prompt governance, caches, documentation, generated design evidence, and KGGraph logs.

## 10. Engineering Quality Checklist

- [ ] Definition, import, publication, project template, attachment, and execution are distinct aggregates.
- [ ] Import, Install, Attach, and Publish are explicit and never auto-chain.
- [ ] Only owned validated account imports are user-publishable.
- [ ] Palette/defaults are project-only; no account-wide installed pointer remains.
- [ ] Attachments have concurrency revision only and no artifact/publication semantics.
- [ ] Project templates/instances cannot edit, release, or publish prompt artifacts.
- [ ] Effective policy uses project-template defaults and downward-only instance overrides.
- [ ] No dataset, package, agent lifecycle, agent-flow, settings, prompt, audit/evaluation, history, provider/tool, cost/usage, or private ID leaks.
- [ ] Explanation tab/state/direct LLM call is retained and unchanged (`DEC-041`); Node Explainer chat coexists through the standard agent workflow.
- [ ] Account/project switches purge mismatched private caches and streams.
- [ ] Tests and KGGraph evidence cover every lifecycle and privacy boundary.
