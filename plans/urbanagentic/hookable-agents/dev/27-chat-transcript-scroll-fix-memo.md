# Implementation Memo: Chat Transcript Scroll + Pinned-to-Newest Behavior

Date: 2026-07-21 (retroactive record, filed 2026-07-24 — bug report and fix were handled conversationally; this memo is the missing durable record)
Status: **implemented** (commit `f1e6782`; recorded as the `COMMIT-f1e6782` amendment on `BL-P4-20260721-13`)

## 1. Problem Statement

The restyled chat panel's transcript did not scroll: `.messages` declared `overflow-y: auto`, but as a **flex child** it would not shrink below its content height (the flexbox `min-height: auto` default), so the transcript grew past the clipped panel and the scrollbar never appeared. Two adjacent gaps became visible once scrolling worked: new replies (and restored history) could land below the fold, and a long *expanded* initial intent could squeeze the transcript to zero height.

## 2. As-Built Fix

- `.messages` gains `min-height: 0`, restoring the scrollbar (the root cause).
- **Pinned to the newest turn**: an effect scrolls the transcript container to the bottom whenever the turns change or the session history finishes hydrating, so live replies and restored conversations are immediately visible.
- The (then-pinned) intent block was capped at 45% height with its own scroll so an expanded prompt couldn't crowd out the transcript. *(Historical note: this cap was removed the same day by `dev/26` when the intent moved into the scrolling transcript — the cap is obsolete, the other two fixes stand.)*

## 3. Verification

Attach suites 28 passed; `tsc` clean at commit time. Behavior is presentation-only: no API, state, or persistence changes.

## 4. Traceability

- Commit `f1e6782`; BL amendment on `BL-P4-20260721-13`.
- Related: `dev/26` (intent-as-first-message) removed the §2 intent-cap portion.
