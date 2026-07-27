# Implementation Memo: Organize and Renumber the Agents Catalog Development Phase

## 1. Problem Statement

The Agents Catalog planning artifacts need a stable numeric order that clearly marks `dev/` as the beginning of a new development project phase. All artifacts created for this plan should remain under `dev/`, retain a recognizable KGGraph Design/Build hierarchy, and use valid bidirectional links.

## 2. Scope

Included: renumber the development-phase index, planning brief, development plan, Design traceability, and Build Log index; update links in all created planning artifacts. Out of scope: changing approved product decisions, implementation requirements, source concepts, KGGraph templates, or application code.

## 3. Recommended Implementation Approach

Use `dev/` as the package root, order phase documents from `00`, and nest KGGraph artifacts by stage:

```text
dev/
  00-development-phase-index.md
  01-development-phase-organization-memo.md
  02-development-plan-brief.md
  03-agents-catalog-development-plan.md
  04-agents-module-encapsulation-memo.md
  05-agents-catalog-implementation-blueprint.md
  06-prompt-to-hookable-agent-migration-memo.md
  07-agent-package-prefix-memo.md
  08-semantic-agent-capabilities-memo.md
  09-agent-import-project-installation-and-privacy-memo.md
  10-agent-plan-decision-closure-and-hardening-memo.md
  11-agent-configuration-modals-and-prompt-governance-memo.md
  12-agent-template-installation-attachment-sharing-lifecycle-memo.md
  13-agent-documentation-consolidation-and-obsolete-plan-removal-memo.md
  14-plan-hardening-and-open-decisions-memo.md
  15-composite-agent-specifications-memo.md
  16-agent-node-package-capabilities-memo.md
  17-hardening-resolutions-memo.md
  aiconn/            (existing sage200 OpenAI-compatible LLM config — default provider source, DEC-039)
  kggraph/
    Stage-2-Design-Phase/2.1-Agents-Catalog-Design-Traceability.md
    Stage-3-Build-Phase/3.1-Agents-Catalog-Build-Log.md
```

This preserves KGGraph stage semantics without mixing feature-specific artifacts into the methodology/example directory.

## 4. Data and State Handling

No runtime data or application state changes. Markdown references are the only derived state and must resolve from their new locations. The numbered development and product specifications are authoritative; generated concepts remain supporting evidence and are explicitly marked when they predate current decisions.

## 5. UI and UX Requirements

The `dev/00-development-phase-index.md` must provide a clear reading order and direct links to the specification, Design traceability, and Build tracking. File names and stage names remain descriptive and stable.

## 6. Edge Cases

- Avoid leaving duplicate copies in old locations.
- Repair references whose relative depth changes after relocation.
- Do not modify unrelated KGGraph methodology files.
- Preserve the Build Log’s future child-log convention under its new stage directory.

## 7. Testing Strategy

Verify the expected files exist only under `dev/`, old paths no longer exist, all relative Markdown targets resolve, and the working-tree changes contain documentation only.

## 8. Acceptance Criteria

- Every file created for the Agents Catalog development plan is contained under `dev/`.
- KGGraph Design and Build artifacts remain separated into correctly named stage directories.
- `dev/00-development-phase-index.md` describes purpose, reading order, source-of-truth rules, and future Build Log placement.
- No stale link points to the previous root `knowledge-graph/Stage-*` locations.
- No application or concept source file is changed.

## 9. Recommended Commit Breakdown

One focused documentation commit: move and encapsulate the planning package, add its index and memo, and update links atomically.

## 10. Engineering Quality Checklist

- [ ] No duplicate planning artifacts remain.
- [ ] KGGraph stage separation is preserved.
- [ ] Relative links resolve.
- [ ] Source-of-truth relationships remain explicit.
- [ ] No implementation code or unrelated documentation is changed.
