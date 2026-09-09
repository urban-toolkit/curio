# dev/76 — Encapsulate the dev/75 transcript-scroll contract under agents/

**Status:** implemented (2026-08-14 — `git mv` into `components/agents/attach/`, imports updated, LLMChat reverted to pre-dev/75 per owner directive; full frontend jest 803 passed / 74 suites (−1 suite: the deleted LLMChat scroll tests), `tsc --noEmit` reports nothing new in touched files). BL-P5-20260814-22. Commit `a99526aa`. Recorded deviations: the initial LLMChat-imports-from-agents decision was superseded mid-implementation by the owner's untouched-LLMChat directive (see §3).
**Date:** 2026-08-13
**Type:** organizational refactor — zero behavior or styling change

---

## 1. Problem Statement

The dev/75 follow-at-bottom scroll contract landed in generic locations:
`TranscriptJumpButton.tsx` + `.module.css` at the `src/components/` root and
`useTranscriptAutoScroll.ts` in the global `src/hook/`. The owner wants agent
chat-specific behavior and UI encapsulated under `components/agents/`, and the
components-root placement litters shared space with chat-transcript chrome.
Expected: the pill, hook, styles, and tests live under the agents feature; all
imports updated; behavior and styling byte-identical.

## 2. Scope

**In:** move `TranscriptJumpButton.{tsx,module.css}` and
`useTranscriptAutoScroll.ts` → `src/components/agents/attach/` (the folder that
already holds `AgentChatPanel` and its sibling feature hooks
`useAgentAttachments`/`useAgentCanvasMutations`); move the hook's test
`tests/hook/useTranscriptAutoScroll.test.tsx` → `tests/attach/` (the mirror of
`agents/attach`, where `useAgentCanvasMutations.test.tsx` already lives);
update import paths in `AgentChatPanel.tsx` and the moved test. **Owner
directive (added during implementation): `LLMChat` must be untouched by the
agents work** — its dev/75 adoption (commit `724ebd3f`) is reverted: the file
returns to its pre-dev/75 content (the `getElementById("messagesDiv")`
unconditional scroll effect) and `tests/components/LLMChat.test.tsx` is
deleted with it.
**Out:** any behavior, styling, markup, or API change to the agent chat
surfaces; the committed dev/75 memo and build-log entry (historical records
keep the old paths and the LLMChat adoption they describe — this memo records
the reversal).

## 3. Recommended Implementation Approach

`git mv` (history-preserving) + mechanical import-path updates. **Resolution of
the LLMChat tension:** the initial move had `LLMChat` (LLM Assistant sidebar,
outside `agents/`) import the agents-owned contract from
`components/agents/attach/`. The owner then directed that `LLMChat` be
untouched by the agents work, so its dev/75 adoption is reverted entirely: the
scroll contract now has exactly one consumer surface — `AgentChatPanel`
(primary and delegated chats) — and lives fully encapsulated under
`agents/attach/` with no cross-feature import. If the LLM Assistant (or any
non-agent transcript) should get the follow-at-bottom behavior later, that is
its own change: adopt the hook and promote it to `src/hook/` at that point.

## 4. Data and State Handling

None — no runtime code changes beyond import specifiers.

## 5. UI and UX Requirements

Pixel- and behavior-identical. The pill keeps its class names, tokens,
animation, aria-label, and focus-fallback contract.

## 6. Edge Cases

- Jest `moduleNameMapper` has a `components/*` alias — all touched imports are
  relative, so no alias updates are needed.
- CSS-module import inside the pill is same-directory (`./…module.css`) and
  moves with it.
- The working tree carries an unrelated pre-existing `console.log` in
  `LLMChat.tsx` — untouched, stays unstaged.

## 7. Testing Strategy

No new tests (organizational change). The moved hook suite plus the existing
`AgentChatPanel` and `LLMChat` suites re-run unchanged — a green full run is
the proof of behavior preservation, `tsc --noEmit` the proof no import was
missed.

## 8. Acceptance Criteria

1. `src/components/TranscriptJumpButton.*` and
   `src/hook/useTranscriptAutoScroll.ts` no longer exist; both live under
   `src/components/agents/attach/`.
2. `AgentChatPanel` imports them as same-directory siblings; nothing outside
   `components/agents/` references them.
3. `LLMChat.tsx` is byte-identical to its pre-dev/75 state (its uncommitted
   pre-existing debug line preserved in the working tree);
   `tests/components/LLMChat.test.tsx` is gone.
4. The hook test lives in `tests/attach/`; the full frontend suite passes with
   no assertion changes; `tsc --noEmit` reports nothing new.
5. Zero diff in the agent chat panels' rendered markup, styles, or behavior.

## 9. Recommended Commit Breakdown

One commit — an atomic move+reimport refactor (splitting would break the build
between commits).

## 10. Engineering Quality Checklist

Single source of truth preserved (no duplication into LLMChat); moves done with
`git mv` for history; no logic edits smuggled in; conventions matched
(feature hooks in the feature folder, test mirror in `tests/attach/`).
