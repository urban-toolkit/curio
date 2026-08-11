# Implementation Memo 67-4: Node Researcher + Verified External Discovery

Date: 2026-08-05
Status: proposed (part of the dev/67 program — see `67-1-index.md`)

## 1. Problem Statement

The Dataset Finder hallucinated Socrata dataset codes during Dataflow Builder sessions
(fix-loop session `89ae8123`); nothing could have caught it, because nothing in the
system can touch the network on an agent's behalf:

- No researcher agent exists (the roster's 16 specs, builtin.py:91-195, contain no
  research coordinate; `dataflow-researcher.md` is an unimplemented brainstorm).
- No web/HTTP tool exists among the 8 registry contracts (tools.py:51-161);
  `resolve_grants` silently drops unregistered tool requests; the providers send no
  `tools=` parameter, so there is no provider-side search either.
- The Dataset Finder's external lane is a display contract: a URL scheme-prefix check
  (content.py:227-235) and honest-labeling prompt text. External picks exit as prose in
  a suggested prompt; the Node Builder writes fetch code around an unverified URL; first
  contact with reality is the user executing the node. The catalog lane, by contrast,
  is server-verified at mint (`_resolve_catalog_dataset`) — the asymmetry is the gap.

Expected (67-0): external discovery is a verifiable research operation — dataset ids,
endpoints, schemas, auth requirements, and response shapes verified before acceptance;
a reusable, chainable Node Researcher other agents can invoke.

## 2. Scope

In scope:
- Backend egress layer: `app/agents/egress.py` — policy-gated HTTP client (SSRF guards,
  scheme/port allowlist, private-address refusal, redirect cap, byte/time caps,
  per-run call budget).
- Tool registry: `web.fetch` (read; GET/HEAD a URL, return status + bounded body/schema
  extract) and `web.search` (read; provider-pluggable search API, results as bounded
  {title, url, snippet} rows; deployment-configured key — absent key → honest
  "search unavailable" tool error).
- Deterministic validators: `app/agents/verify.py` — `verify_socrata(domain, id)`
  (probe `https://<domain>/api/views/<id>.json`, extract name/columns),
  `verify_endpoint(url)` (HEAD→GET fallback, status/content-type/sample keys) — direct
  code, no model in the loop.
- Roster: `agent.node-researcher@1.0.0` — capability `research.verify` (+
  `research.summarize`), tools `web.search`, `web.fetch`; instruction file
  `research_instruction.txt` (verify-then-report, citations + retrieval dates, "never
  invent an identifier; report failure to verify as a finding").
- Chainability: `delegatesTo` additions — Dataset Finder, Node Builder, Node Content
  Builder, Dataflow Builder gain `agent.node-researcher` for `research.verify`
  (delegation.py already resolves capability-first; a missing researcher mints the
  existing reviewed `project.install` proposal).
- Dataset Finder verification gate: external candidate rows gain
  `verification: {status: verified|unreachable|unverified, checkedAt, evidence}` —
  populated by a deterministic verify pass at part-parse time in the finder's run (URL
  rows probed via `egress`), rendered on the card (verified badge / warning); the
  handoff prompt carries the evidence. Rows the model marks with a datasetId-like code
  but no probeable URL are labeled unverified loudly.
- Ledgers: DEC-053.

Out of scope: provider-native web search (follow-up behind the same policy);
auto-rejecting unverified rows (the user decides — the card just stops laundering);
crawling/multi-page research beyond N bounded fetches per run; LangChain adoption (see
§3 decision); the fetch-node authoring flow itself (dev/50 handoff unchanged).

## 3. Recommended Implementation Approach

**A. Egress before everything (DEC-053).** One module owns policy: https(+http) only,
default-deny private/link-local/loopback ranges AFTER DNS resolution, 5 redirects, 256KB
body cap, 10s timeout, ≤4 egress calls per run (tool budget), full request log on the
execution record (URL, status, bytes — auditability). No other module speaks HTTP for
agents.

**B. Tools, then validators, then the agent.** `web.fetch`/`web.search` are ordinary
read contracts in the existing loop (grants per-coord, results framed as untrusted
context — the dev/41 framing already exists). `verify.py` composes egress calls into
yes/no+evidence answers — used BOTH by the researcher's run (as tool results it reasons
over) and directly by the Dataset Finder's verification gate (no model needed to check
a Socrata id). The researcher is a normal roster agent: other agents reach it through
the existing delegation seam (depth-1, structurally proposal-less per DEC-046 — its
REPLY is evidence, never a mutation).

**C. The Dataset Finder stops laundering.** External rows with a URL are probed
deterministically during the run (bounded: first 4 rows); `verification` rides the part
(content.py row schema + card rendering). The discovery instruction adds: identifiers
must come from a tool result (web.search/web.fetch/catalog.search) or be labeled
UNVERIFIED in the row and the prose. Mint-side (dev/50's `dataset.fetch.author`
handoff): the composed Node Builder prompt includes the verification evidence or the
unverified warning verbatim.

**D. LangChain decision (the 67-0 directive).** Evaluated for the research chain
(search → fetch → extract → confirm): the chain is ≤3 deterministic steps around one
model synthesis, fits the existing bounded tool loop (MAX_TOOL_ROUNDS) and delegation
seam, and the validators must stay boring direct code regardless. Recommendation:
direct code now; `delegation.py` remains the adapter seam; record "unbounded research
chains" alongside DEC-021 as LangChain's monitored re-open conditions. No LangChain
dependency lands in this memo.

## 4. Data and State Handling

- Verification evidence is part data (rides the candidates part + execution record),
  never a new store; re-runs re-verify (freshness over caching; the checkedAt timestamp
  makes staleness visible).
- Egress results never persist beyond the run except as bounded evidence strings.
- Failure modes are data: unreachable → `unreachable` + status; timeout → `unreachable`;
  search key absent → tool error the model must surface honestly.

## 5. UI and UX Requirements

- Candidates card: verified badge (✓ + checkedAt) / unverified warning per external row;
  URL rendering unchanged otherwise; the confirmation prompt carries the evidence.
- No new surfaces for the researcher — it is an installable agent like any other; its
  chat works standalone AND as a delegate.

## 6. Edge Cases

- SSRF attempts (`http://169.254.169.254/…`, `http://localhost:…`, DNS-rebind hosts) →
  refused by egress policy (tested explicitly).
- Redirect to a private address → refused at the hop.
- Socrata id valid but dataset private/404 → `unreachable` with the status as evidence.
- Huge responses → byte-cap truncation marker, schema extract from the truncated head.
- Model cites a verified row's URL but swaps the id in prose → the handoff prompt is
  composed from the ROW, not the prose (structure wins).
- Researcher not installed when delegated to → existing reviewed install proposal.
- No search API key configured → web.search errors honestly; web.fetch still verifies
  direct URLs.

## 7. Testing Strategy

- Egress policy unit tests (allowlist, private ranges post-DNS, redirects, caps) with a
  fake resolver/transport — no real network in CI.
- Validator tests over canned Socrata/API fixtures (ok, 404, timeout, truncated).
- Tool loop: web.fetch grant → framed result; budget enforcement; ungranted agents
  unchanged.
- Finder gate: external rows verified/flagged; card render; handoff prompt carries
  evidence (route-level with a fake egress).
- Delegation: Dataflow Builder → researcher `research.verify` end-to-end with a fake
  transport; missing researcher → install proposal.

## 8. Acceptance Criteria

- [ ] An invalid Socrata code in an external candidate row surfaces as an explicit
      UNVERIFIED/unreachable marker on the card and in the handoff — it can no longer
      arrive silently in a fetch node.
- [ ] Any builder agent can delegate `research.verify` and receive evidence with
      citations/dates; the researcher never mutates anything.
- [ ] Egress is impossible outside the policy module, and every egress call is on the
      execution record.

## 9. Recommended Commit Breakdown

1. Backend: egress policy module + tests (no consumers).
2. Backend: web.fetch/web.search contracts + verify.py + tool-loop tests.
3. Backend: researcher roster entry + instruction + delegation wiring + tests.
4. Backend+frontend: Dataset Finder verification gate + card badges + tests.
5. Docs: DEC-053 ledgers + BL-P5 entry + dev/49 LangChain note update.

## 10. Engineering Quality Checklist

- Deterministic validators are model-free; the model only synthesizes over evidence.
- One egress chokepoint with default-deny policy; auditable per run.
- Verification is visible data, never a silent gate that hides rows.
- The delegation seam is reused untouched (DEC-046 guarantees hold for the researcher).
