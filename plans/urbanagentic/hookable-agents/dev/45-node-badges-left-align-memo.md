# Implementation Memo: Node-Attached Agent Badges — Consistent Left Alignment

Date: 2026-07-29
Status: implemented 2026-07-29 (same session)
Feature slice: CSS-only layout fix to the node badge row; no behavior, ordering, spacing, or styling changes.

## 1. Problem Statement

`NodeAgentBadges`' container is anchored to the node's horizontal center: `.badges { left: 50%; transform: translate(-50%, 6px); }`. A centered flex row grows symmetrically, so the badges' on-screen position depends on how many agents are attached — one badge sits centered under the node, each additional badge shifts the whole row leftward and rightward. The requested behavior: badges start at the node's left edge and grow rightward, stable regardless of count.

## 2. Scope

`NodeAgentBadges.module.css` only — the anchor becomes `left: 0; transform: translateY(6px);`. Everything else is untouched: `top: 100%` (below the node), the 6px vertical offset, `gap: 6px`, flex row ordering, z-index, pointer-events, the shared `AgentAvatarBadge` chips, hover tooltips, click/detach behavior, and the canvas dock (a different, deliberately centered surface — out of scope).

## 3-6. Approach, Edge Cases

One anchor change; the row now left-aligns to the node's left edge for 1..n badges with no per-count drift. Overflow beyond the node's width extends rightward (previously it extended both ways) — strictly more predictable. No RTL handling exists elsewhere in the canvas; none added.

## 7. Testing

CSS-module values are identity-proxied in jest (class names only, no computed styles), so this positional change has no meaningful unit-level assertion; verification is visual. All existing suites must stay green (`NodeAgentBadges`/`AgentAvatarBadge` tests cover structure and behavior, which are unchanged).

## 8. Acceptance Criteria

- [x] Attached-agent badges are left-aligned to their node for any count; adding/removing an agent never shifts the existing badges.
- [x] Spacing (6px gap and offset), ordering, interactions, and visuals are unchanged; the canvas dock is untouched.

## 9. Commit

One commit: `fix(agents): left-align node-attached agent badges (+ this memo)`.
