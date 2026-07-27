# Prompt Architecture: Prompts as Manifest-Defined Hookable Agents

The application's existing prompts become **versioned hookable agents**. Each prompt-backed
agent is a self-contained artifact under `agents/`, with a manifest that links to its
package-local system and instruction prompt files, input/output schemas, compatible hook
targets, provider requirements, and runtime/review policy. High-level agents such as the
Dataflow Builder delegate to these agents through the stable runtime interface rather than
invoking raw prompt filenames.

```text
PromptAgent = { manifest, prompt_assets, input_schema, output_schema }
Orchestrator.reason():
    plan  = run(agent("agent.dataflow-task-planner"), context)
    for subtask in plan:
        out = run(agent(for_role(subtask)), subtask_context)
        if installed_and_enabled("agent.generated-content-evaluator"):
            ok = run(agent("agent.generated-content-evaluator"), out)
        else:
            ok = validation_unavailable("authoritative evaluator package not installed")
    ...
```

Prompt loading remains centralized in backend `agents/infrastructure/prompts`, but the
registry resolves manifest assets through the active project's installed templates; it is not the
product identity of the behavior.
Prompt editing, evaluation, release, and audit are separate governance services under the backend
`agents/` boundary; the browser never writes package files or supplies a trusted filesystem path.

## Semantic capabilities vs. prompt assets

Each manifest declares semantic `capabilities[]` separately from `prompts`. Capabilities
describe stable behavior and typed contract versions; prompts are package-local implementation
files for one agent version.

```text
capability: node.explain
implemented by: agent.node-explainer@1.0.0
instruction asset: prompts/single_box_explanation_prompt.txt
```

Orchestration requests a capability, not a prompt filename. Resolution considers contract
version, hook target, provider/tool requirements, trust, project installation, and version policy,
then persists the exact selected definition on each execution. `_prompt`, `.txt`, and path-like values are invalid
capability IDs.

The selected implementation is persisted as an immutable artifact coordinate containing the
publisher namespace, agent ID, exact version, and digest. Capability declarations guide
resolution but never grant context or tool permissions.

## Roles

Planning · Content Generation · Workflow Construction · Validation · Analysis ·
Debugging · Explanation · Evaluation · Refinement.

## Prompt-backed agent roster

| Agent ID | Semantic capabilities | Prompt asset | Role(s) |
| --- | --- | --- | --- |
| `agent.dataflow-task-planner` | `workflow.plan.create` | `prompts/new_subtasks_prompt.txt` | Planning |
| `agent.execution-subtask-planner` | `execution.followup.plan` | `prompts/new_subtask_from_exec_prompt.txt` | Planning from execution feedback |
| `agent.workflow-suggester` | `workflow.suggest` | `prompts/workflow_suggestions_prompt.txt` | Planning / Workflow Construction |
| `agent.task-refresh-agent` | `workflow.plan.refresh` | `prompts/task_refresh_prompt.txt` | Refinement / re-plan |
| `agent.node-content-builder` | `node.content.generate` | `prompts/new_content_prompt.txt` | Content Generation |
| `agent.chat-agent` | `conversation.respond`, `attachment.refine` | `prompts/chat_prompt.txt` | Conversation / refinement |
| `agent.connection-builder` | `connection.propose` | `prompts/new_connection_prompt.txt` | Workflow Construction |
| `agent.keyword-binding-agent` | `workflow.keyword.bind` | `prompts/keywords_binding_prompt.txt` | Workflow Construction / Analysis |
| `agent.plan-coherence-validator` | `workflow.coherence.validate` | `prompts/evaluate_coherence_subtasks_prompt.txt` | Validation |
| `agent.syntax-analysis-agent` | `code.syntax.analyze` | `prompts/syntax_analysis_prompt.txt` | Validation / code analysis |
| `agent.generated-content-evaluator` | `content.quality.evaluate` | `prompts/evaluate_generated_content_prompt.txt` | Evaluation; blocked until missing asset is approved |
| `agent.debug-agent` | `code.debug.diagnose`, `code.fix.propose` | `prompts/debug_prompt.txt` | Debugging |
| `agent.dataflow-explainer` | `dataflow.explain` | `prompts/explanation_prompt.txt` | Dataflow explanation |
| `agent.node-explainer` | `node.explain`, `node.output.interpret` | `prompts/single_box_explanation_prompt.txt` | Node explanation |

## Orchestration and delegation

| High-level agent | Prompt-backed agents delegated to |
| --- | --- |
| **Dataflow Builder** | Dataflow Task Planner, Execution Subtask Planner, Task Refresh, Workflow Suggester, Plan Coherence Validator, and other specialists required by its plan. |
| Dataset Finder | Workflow Suggester and Keyword Binding Agent. |
| Node Builder | Node Content Builder and Execution Subtask Planner. |
| Validation | Plan Coherence Validator, Generated Content Evaluator, and Syntax Analysis Agent. |
| Optimization | Generated Content Evaluator and Task Refresh Agent. |

Direct attachment is also supported where a manifest declares a compatible target. The user first
chooses `Install in project` from Global Catalog or My Imports, then attaches from that project's
palette; delegation is not required.

## Package-local prompt links

Every agent artifact contains `manifest.json`, prompt assets, and contract schemas. A manifest
references prompts with safe relative paths and SHA-256 digests. Most agents link
`prompts/default_preamble.txt` plus their instruction file; Syntax Analysis Agent links
`prompts/syntax_analysis_preamble.txt`. Absolute paths, traversal, symlink escape, missing
files, and digest mismatches are invalid.

The current checkout does not contain `evaluate_generated_content_prompt.txt` or a call site.
That agent is not registered until authoritative prompt content and input/output contracts are
approved; another prompt must not be silently substituted. The other thirteen independently
valid packages can be registered, tested, and released without it.

## Prompt Settings And Governance Lifecycle

The shared Agent Settings modal exposes three prompt-specific screens alongside Cost, Quotas,
and Resource policies:

- **Prompt quality** runs versioned contract/static/regression checks and, where separately
  approved, an LLM rubric. Every run pins the exact artifact or draft revision, suite/rubric
  version, thresholds, provider profile, and evaluator artifact coordinate. Results include
  status, findings, score, usage/cost, and whether a newer edit made them stale.
- **Prompt editor** lets the owner of a validated **My Imports** definition edit package-local prompt content in a
  revisioned draft, inspect declared variables/schemas, preview composition, and review a
  semantic diff. A third-party, built-in/global, project-template, or attachment prompt remains
  read-only. Any future fork/export must be packaged and explicitly re-imported and is out of scope.
- **Prompt audit** pins versioned privacy/security/compliance rules, records audit runs/findings,
  and exposes an authorized, append-only governance history for draft changes,
  validation/evaluation outcomes, release, project-template update, attachment migration, and
  publication. Events identify actor, time, reason, before/after hashes, and linked records while
  redacting secrets and private execution context.

```text
owned explicitly imported exact artifact
        │ create private draft
        ▼
revisioned prompt draft ── edit/validate ──► pinned quality evaluation
        │                                      │
        └──────────────── audit events ◄───────┘
                               │ approved release
                               ▼
                    new immutable version + digest
                               │
                 explicit project install/update / attachment migration / publish
```

Neither `Save draft` nor a quality score changes an imported artifact, project template, or
attachment. Release constructs a new private imported-definition package and exact coordinate.
Installing/updating it in a project, migrating an attachment, and publishing it globally are
separate reviewed actions. Evaluation never automatically releases, installs, migrates, or publishes.

Prompt Quality must not be conflated with `agent.generated-content-evaluator`. Contract, static,
and curated regression checks may run independently. An LLM-as-judge step is available only when
an explicitly approved evaluator artifact and provider policy are configured; otherwise that step
is shown as unavailable. OQ-007 therefore remains closed-fail for the missing agent rather than
being bypassed by the settings UI.

Drawer `Agent settings` opens account policy. Owned My Imports `Definition settings for <agent>`
opens these editable governance screens. `Project agent settings` and chat `Attachment settings`
show prompt source/evaluation/audit evidence read-only; project templates and instances cannot
Release or Publish. Manifest `settingsDefaults` are immutable validated seeds; each project
installation materializes its own private revisioned policy profile, Reset re-clamps current
account/deployment ceilings for that project, and attachment overrides only tighten.
The shared result exposes no settings entry point and cannot enumerate prompt bodies,
drafts, evaluations, audits, definitions, templates, or attachments.
The chat transcript remains execution history; Prompt Audit remains compliance findings plus
governance history.

## Principles

- **Single source of truth** — prompt text lives in one versioned agent artifact, never in UI,
  orchestration code, or duplicate registries. Mutable editor state lives only in a revisioned
  draft until a new artifact is released.
- **Hookable product identity** — every prompt behavior is discoverable as a reusable definition,
  privately importable, publishable only through eligible ownership, explicitly installable in a
  project, attachable, configurable, and independently testable through its versioned manifest.
  Attached instances themselves are not versioned artifacts.
- **Framework-agnostic** — manifests and prompt assets are framework-neutral; the LangChain
  adapter loads them behind `AgentRuntime`.
- **Capability-based composition** — orchestrators request semantic capabilities and typed
  contracts; explicit agent IDs are used only for required/preferred delegates, never raw filenames.
- **Fail closed** — missing/untrusted prompt assets prevent publication, installation, and run.
- **Reproducible quality** — evaluations pin prompt/draft, suite, thresholds, provider, and any
  evaluator; a later edit makes prior results visibly stale rather than rewriting them.
- **Auditable immutability** — prompt changes create append-only governance events and a new
  imported-definition release; project templates and existing attachments are never edited in place.

## Node Explanation Migration And Sharing

`agent.node-explainer` plus `prompts/single_box_explanation_prompt.txt` is the agent-based
node-explanation path. Per `DEC-041` (`dev/18`) the built-in node Explanation tab, its direct raw
prompt/provider call, and its tab state/cache are **retained permanently** and coexist with the
agent path; the removal formerly planned here is cancelled. An `Explain with Node Explainer`
affordance may additionally lead through project install → attach → unified chat.
`agent.dataflow-explainer` remains the separate canvas/full-flow explanation behavior.

Prompt assets, definitions, imports, project templates, attachments, evaluations/audits, and chat
history are not exposed in the shared result. The public result view surfaces no providers,
palettes, agents, settings, execution, `Save a copy`, or project clone.
