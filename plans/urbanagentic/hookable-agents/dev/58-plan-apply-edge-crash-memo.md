# Implementation Memo: Plan-Apply Edge Crash (dev/52 bridge follow-up)

Date: 2026-08-05
Status: implemented 2026-08-05 — see log. Verification: frontend `npx jest` → 660 passed
(61 suites); the bridge edge-item shape is regression-pinned.

## 1. Problem Statement (root cause, from the user's stack trace)

The dev/52 `graph-created` bridge inserts edges as `{id, source, target, handles, type,
markerEnd}` — **without a `data` object**. `UniDirectionalEdge` (and `BiDirectionalEdge`) read
`data.keywordHighlighted` unguarded, so the first render of a bridge-inserted edge throws,
React's error overlay swallows the whole canvas update, and the just-inserted graph never
paints. The backend apply had already succeeded — hence "after refresh the nodes have been
created correctly" (`loadTrill` always sets `add_edge.data = {}`, which is why loaded edges
never crash).

## 2. Approach (both layers)

- Bridge parity: the `graph-created` edge items carry `data: {}` exactly like `loadTrill`'s.
- Component hardening: `data?.keywordHighlighted` in both edge components — a missing optional
  display flag must never take down the canvas render, whatever path created the edge.

## 3. Tests / Acceptance

- Bridge unit test asserts the inserted edge item carries `data: {}`.
- Edge components render without `data` (regression for any future data-less path).
- [x] Applying a plan paints the graph live with no runtime error overlay.

## 4. Commits

1. `Plan-apply edge crash: bridge edge data parity + guarded edge components (dev/58)`
2. Docs: memo implemented + BL-P5 amendment.
