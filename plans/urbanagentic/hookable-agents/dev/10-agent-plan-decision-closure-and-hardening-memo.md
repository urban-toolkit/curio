# Implementation Memo: Agent Plan Decision Closure and Privacy Hardening

Status update (2026-08-24): decision record partially implemented. `DEC-041` supersedes every former Explanation-removal instruction; `DEC-055` and `DEC-057`/`DEC-058` close OQ-007/OQ-008. ProviderProfile/encrypted-secret migration, durable multi-instance recovery, governance surfaces, and deployment gates remain.

## 1. Problem Statement

The plan must preserve exact immutable definition identity, provider/egress safety, recovery, hostile-input handling, settings governance, and prompt audit while adopting memo `12`'s superseding lifecycle. Retaining account-wide installation pointers or attachment SemVer/publication would reintroduce ambiguous ownership and cross-project leakage. The node Explanation direct caller is the explicit exception: `DEC-041` retains it as an independent surface and tests prevent double execution with Node Explainer chat.

## 2. Scope

Included: exact `AgentDefinitionArtifact` identity; bounded explicit account Import; explicit project template Install; imported-definition-only user Publish; private unversioned attached instances; distinct deletion/unpublish/quarantine/GC; provider profiles/egress; execution recovery; Node Explainer migration; settings/prompt quality/compliance audit; retention/backup gates; tests and traceability. Out of scope: implementation, automatic lifecycle chaining, publishing/sharing templates or instances, live shared projects, project-private prompt overrides, final `OQ-008` durations, supplying `OQ-007`, multi-tenant collaboration, or generated artifact regeneration in this pass.

## 3. Recommended Implementation Approach

Adopt the fixed private lifecycle:

```text
immutable AgentDefinitionArtifact
  -> explicit AccountImportedAgent (private; user-publish eligible when owned/validated)
     OR visible built-in/global definition
  -> explicit ProjectAgentTemplate (one project's palette/defaults)
  -> explicit AttachedAgentInstance (private target derivation; attachmentId + revision only)
  -> private execution/events
```

Import, Install, Attach, and Publish are separate idempotent commands. Only owned validated imports may use user Publish. Attachments have no SemVer/release/publish lifecycle; executions pin source definition/prompt/project-settings/attachment/provider/effective-policy inputs. Project palettes/defaults are isolated by project.

Retain prior hardening: content-address immutable definitions; reject publisher/ID/version digest collisions; use bounded contained archive staging and atomic visibility; allow only typed server-registered tools; keep provider credentials behind opaque account profiles; enforce explicit egress/SSRF policy with no local-to-cloud fallback; sanitize agent content centrally; use leases/fencing/interrupted status and linked explicit retry without automatic side-effect replay.

## 4. Data and State Handling

- Keep definition artifacts, account imports, global publications, project templates/defaults, private instances, sessions/executions/events, trust restrictions, provider profiles, settings/snapshots/reservations/usage, and prompt governance as separate stores.
- Import atomically commits one immutable artifact and private import record; it never writes a project/publication.
- Install atomically creates one project template and isolated settings profile; only that project's palette cache changes.
- Attach locks/validates project/template/target and creates an unversioned private instance/session. Project uninstall checks only that project's live references and never detaches silently.
- Updating/releasing/publishing an imported definition never mutates project templates or attached instances. A project template source update and attachment migration are separate reviewed actions.
- User Publish accepts only an owned validated `AccountImportedAgent`; normal unpublish changes discovery, quarantine blocks unsafe digests, and reference/retention-aware garbage collection remains separate.
- Effective policy is deployment ∩ account ∩ project-template defaults ∩ attached-instance downward-only override ∩ atomic reservation. Persist all contributing revisions on the execution.
- Prompt Edit/Quality/Compliance Audit/Release belongs only to owned definitions created through explicit account Import. Built-in/global definitions, project templates, and instances expose source evidence read-only when authorized. Any future fork/export must be packaged and explicitly re-imported and is out of scope.
- Clear project-keyed palette/template/instance/session/settings state on project switch; clear all account-private imports/prompts/evaluation/audit/provider state on account switch.

## 5. UI and UX Requirements

- Distinguish `Global Catalog`, `My Imports`, and `Installed in this project`; show separate Import, Install in project, eligible imported-definition Publish, and Attach actions.
- Project templates and attached instances show no Publish/Release/version action. Instances show private project scope, source template, target, status, chat, and settings.
- Cost/Quota/Resource settings use account policy, project-template default, and instance downward-only scopes. Prompt screens author only owned imports; lower scopes are read-only provenance/evidence.
- Retain the node Explanation tab/menu/state/cache/direct call (`DEC-041` — the removal is cancelled). Node Explainer project Install → Attach → unified chat is a coexisting path with its own errors/retries/settings/history.
- Preserve WCAG 2.2 AA, safe renderer, focus restoration, non-color states, reduced motion, zoom/reflow, and accessible conflict/interrupted/denied feedback.

## 6. Edge Cases

- Repeated/concurrent Import/Install/Publish/Attach or a fabricated Publish from a built-in/global/project-template/instance.
- Same definition installed in multiple projects with different defaults; project switch/account switch during pending mutations or streams.
- Imported definition unpublished/deleted/released while project templates/execution pins retain source bytes.
- Project uninstall races with attach/review/execution; concurrent instance edits conflict without creating a version.
- Remote provider is forbidden, local provider unavailable, credentials revoked, or custom endpoint targets restricted networks.
- Server restarts after uncertain provider/tool work; no automatic replay.
- Node Explainer missing/provider-blocked/over quota; its chat path does not silently fall back to the independent retained Explanation-tab caller.
- Prompt candidate self-evaluates, audit evidence is stale, or secret remediation/retention/backup rules interact.

## 7. Testing Strategy

Add lifecycle contract/integration tests for explicit definition/import/project-template/instance transitions, idempotency, imported-only publication, project isolation, attachment revision without SemVer, update pin preservation, and separate lifecycle commands. Add bounded import, digest collision, provider secret/egress/SSRF, safe rendering, tool authorization, lease/interruption/retry, settings reservation, prompt governance, and backup/restore tests.

Add Node UI/import-boundary tests proving the retained Explanation tab still works (`DEC-041`) and one Node Explainer chat action causes one governed execution.

## 8. Acceptance Criteria

- Only explicit Import creates an account-private reusable definition, with no automatic project/publication change.
- Only owned validated imports can use user Publish; Install and Publish are independent.
- Explicit project Install creates project-only palette membership/defaults.
- Attached instances are private project derivations with `attachmentId` plus concurrency revision only and no SemVer/Release/Publish.
- Node Explainer chat is a coexisting node-explanation path alongside the retained Explanation tab (`DEC-041`).
- Credentials/egress/tools/import/rendering/recovery/settings/prompt governance remain fail-closed and auditable.
- `OQ-007` and `OQ-008` are closed by `DEC-055` and `DEC-057`/`DEC-058`; the evaluator is report-only, and retention/deletion claims follow lifecycle-bound deletion plus operator-declared backup posture.

## 9. Recommended Commit Breakdown

1. Align lifecycle/identity/privacy decisions and remove account-install/attachment-version assumptions.
2. Add bounded private Import and imported-only publication authorization.
3. Add explicit project template/palette/default lifecycle and private instances.
4. Retain and regression-test the Explanation tab/direct caller while adding Node Explainer chat as an independent governed path (`DEC-041`).
5. Add provider/recovery/import/render hardening and lifecycle regressions.
6. Align settings/prompt governance at imported-definition/project-template/instance scopes.
7. Reconcile KGGraph/docs and later regenerate design/workbook artifacts.

## 10. Engineering Quality Checklist

- [ ] Definition/import/publication/project template/instance/execution are distinct.
- [ ] Import/Install/Attach/Publish never auto-chain.
- [ ] Only owned validated imports are user-publishable.
- [ ] Project palette/defaults never leak across projects.
- [ ] Attachments are unversioned private derivations; executions hold reproducibility pins.
- [x] Explanation UI/direct caller is retained and regression-tested; Node Explainer chat coexists without implicit fallback or double execution (`DEC-041`).
- [ ] Secrets, egress, tools, hostile imports/content, and recovery fail closed.
- [ ] Settings and prompt governance use the revised scopes without weakening policy.
- [ ] Retention/backup questions remain explicit and no deletion claim is overstated.
- [ ] Tests and KGGraph evidence cover every decision/risk.
