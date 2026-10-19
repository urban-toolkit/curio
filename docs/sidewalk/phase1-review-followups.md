# Phase 1 review follow-ups

Recorded October 19, 2026 during submission follow-up. These are **open follow-up work**, not fixes delivered by this draft. The implementation and previously recorded functional results remain unchanged. The prepared branch was renamed from `codex/sidewalk-inspection-pr` to `feat/sidewalk-inspection` without rewriting its existing commits.

## 1. Fetcher server limits, bounds validation and authentication

Owner: **urban-toolkit/curio**, Street Vision backend and its host authentication integration.

`utk_curio/backend/app/streetvision/routes.py` currently validates only that the bounding box is a four-item list. It does not establish finite numeric WGS84 values, coordinate ranges, valid ordering or an explicit antimeridian policy. The fetch limit is converted with `int(...)` outside the route's error handler and has no enforced server-side maximum. In `services/streetview.py`, that limit determines the sampling grid and therefore can increase provider requests and work substantially. UI limits and the 512-entry image cache are not server request budgets.

The Street Vision routes do not currently apply Curio's authenticated-user guard or per-user authorization. An opaque image token hides the provider key but is a bearer reference, not an authenticated ownership check. Follow-up: use the established Curio authentication/authorization contract for Fetcher operations and image access, define server-enforced result/sample/concurrency/time budgets, validate request types/ranges and return clear client errors. Cover unauthenticated requests, invalid and oversized bounds/limits, and bounded provider work with backend fixtures. No new limits, validation or authentication are implemented in this submission follow-up.

## 2. Provider failures reported as successful empty results

Owner: **urban-toolkit/curio**, Street Vision service/routes and Fetcher error presentation.

`fetch_images_in_bbox()` catches request failures and continues, and skips every metadata response whose status is not `OK`. It does not distinguish legitimate `ZERO_RESULTS` from authorization, quota or other provider errors; it also omits `raise_for_status()` on this path. Consequently, a failed search can return an empty FeatureCollection with HTTP 200 and appear successful. Coverage already raises for explicit non-`ZERO_RESULTS` provider statuses, but catches transport failures and continues, so an all-transport-failure sample can still appear as zero coverage. These Fetcher limitations are separate from Panorama's request/camera confirmation safeguards.

Follow-up: propagate specific sanitized transport/HTTP/provider failures, distinguish no imagery from failed or partially failed sampling, define retry/partial-result behavior and ensure the UI does not report failure as a successful empty result. Use reproducible fixtures for denied, quota-limited, transient, malformed and truly empty responses. No error-handling behavior is changed here.

## 3. Reproducible first-tile activation in the portable example

Owner: **urban-toolkit/curio**, Sidewalk example/package integration, coordinated with the documented Autark selection prerequisites.

The exported graph imports and prepares resources, but its keyed Before-map events do not automatically open an editing tile on current upstream. Navigation arrows require an already active tile; the positional legacy chooser is not a reproducible activation procedure for this keyed workflow. The walkthrough therefore lacks a verified clean-import procedure to activate the **first** tile and begin editing/inspection. The earlier successful import/Run all check does not establish that procedure.

Follow-up: define and verify an explicit supported first-tile activation path from a clean import, retaining Before picking, independent PCP state and the exact interaction semantics. Document the action and expected tile. Do not infer clicks, seed invented map metadata, replace the map/PCP grammar or claim end-to-end editing acceptance from the current example. No activation workaround is implemented here.

## 4. Integration verification against newer upstream main

Owner: **urban-toolkit/curio** integration review; native map and optional Grammar event changes remain owned by their [separate repositories](map-selection-investigation.md).

Functional checks were recorded on implementation commit `34cb5532e2e7573743cb081893f371e61b1b6325`, based on main `6a4721c0afb0f6bca23c9c1ff55ad851eab86341` (0.16.452). They are not evidence of compatibility with later main commits. This branch/documentation follow-up does not update the base, rebase, rebuild or rerun those suites.

Follow-up: record the then-current main SHA, integrate in an isolated checkout without rewriting this review history, and rerun required package discovery, behavior replacement, input/execution, selection/PCP and persistence checks against that exact version. Keep the [saved-grammar discrepancy](phase1-verification.md#remaining-limits) separate and require a real save/reopen verification before claiming reliability. Preserve the original running installation.

See the [implementation manifest](../../packages/curio.sidewalk-stewards@1/IMPLEMENTATION.md), [recorded functional results](phase1-verification.md), [selection investigation](map-selection-investigation.md) and [complete capability table](consolidated-capability-table.md). The Phase 1/2/3 roadmap is unchanged.
