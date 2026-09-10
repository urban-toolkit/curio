# dev/130 — Web search as a first-class tool on the OpenAI SDK path: native function calling, always reachable while solving a node, and the Dataset Finder validating the connections it proposes

**Status: PROPOSED (2026-09-10) on `imp/agentcatalog` @ `87036e63`. Every line number below was
read on that commit.**

Date: 2026-09-10
Branch / tree: `imp/agentcatalog` @ `87036e63` (dev/129 commit 6).
Origin: owner instruction — *"To help solving the dataflow Implement the web search tool in the
OpenAI SDK for communicating with the LLM. It must always be used by any agent whenever it sees a
need when trying to solve a node, especially the Dataset Finder agent, to validate external
dataset API connections."* — with a walkthrough of the two ways to reach web search through an
OpenAI-shaped API: **Scenario A**, function calling plus an orchestration loop (what a local
Gemma-class server needs, since it cannot crawl), and **Scenario B**, the hosted Responses API's
native `{"type": "web_search"}` tool.
Family: dev/41 (`DEC-006`/the fenced `toolRequest` protocol) → dev/67-4 (`DEC-053`, the egress
chokepoint + `web.search`/`web.fetch`) → dev/90 A1/A2/A3 (the Researcher, trusted hosts, keyed
public providers, `CURIO_SEARCH_URL`) → dev/95 (`DEC-065`, runtime-gathered search results as
delegate INPUTS) → dev/114/126 (the Dataset Finder's two lanes) → dev/127/128/129 (the repair
loop's inputs and gates) → **dev/130 (this memo)**.
Design decisions consumed: `DEC-053` (every outbound call through one policed chokepoint),
`DEC-046` (a delegate is structurally tool-less; the runtime supplies its inputs), `DEC-063`,
`DEC-017` (a tool declaration is never a grant), `DEC-072` (a URL is a source only once verified),
`RISK-SECRET-001`.

---

## 0. What exists today, precisely

The capability is built; the wiring the owner asks for is not.

- **The tools exist.** `web.search` and `web.fetch` are declared tool contracts (`tools.py:80`-`:90`),
  executed behind the `DEC-053` chokepoint with a per-run budget (`egress.MAX_CALLS_PER_RUN = 4`),
  and `web.search` reads a deployment-configured provider template (`CURIO_SEARCH_URL`,
  `tools.py:642`) with an honest *"not configured"* answer when there is none.
- **The orchestration loop exists** — and it is exactly the owner's Scenario A, one layer up from
  the SDK: the model emits a `curio.v1` fenced `toolRequest`, the runtime executes the granted
  read, feeds the result back, and re-prompts, bounded per run (dev/41). It was built fence-first
  deliberately, because a local Gemma-class model that ignores `tools=` still emits a fence.
- **The SDK is not told about the tools.** `run_chat_completion`'s `openai_compatible` branch
  (`providers.py:114`-`:123`) builds `create_kwargs` with messages and token limits only: no
  `tools=[…]`, no `tool_choice`, and nothing reads `choice.message.tool_calls`. A model that
  WOULD have used native function calling never learns the tools are there.
- **Almost no agent can search.** Only `agent.node-researcher` (`builtin.py:187`) and
  `agent.researcher` (`:396`) hold the web contracts. The **Dataset Finder holds
  `catalog.search`, `dataset.install`, `dataflow.read`** (`:243`) — so its external lane is
  *model-suggested* rows that the runtime then probes (`verify.verify_external_source`). It never
  searches, and it cannot check an API's shape beyond a reachability probe.
- **A node-solving child holds nothing.** `agent.node-content-builder` declares no tools at all
  (`builtin.py:126`-`:133` lists reads, not web access), by `DEC-046`'s design: a delegate is
  tool-less and the runtime hands it inputs. So "any agent whenever it sees a need when trying to
  solve a node" cannot mean "grant the child web tools" — it has to mean the runtime searches on
  its behalf, which is the dev/95 pattern already used for the Researcher's notes.

---

## 1. Problem Statement

**D1 — the SDK path hides the tools from models that support them.** Every provider gets the same
fence-only prompt. For an endpoint that implements OpenAI function calling (OpenAI itself, vLLM,
Ollama's newer builds, Groq, sage200's compatible layer), the runtime is choosing the weaker of
two protocols and cannot tell whether the model would have used the stronger one.

**D2 — search is unreachable exactly where the owner needs it.** A data-loading node's fetch code
must name a URL the runtime verified (`DEC-072`). Today the only way a URL becomes verified is a
probe of a URL someone already guessed: the child cannot search for the right endpoint, and the
Dataset Finder — the agent whose entire job is finding sources — cannot either.

**D3 — "validate external dataset API connections" is not what a probe does.** `verify_external_source`
answers *is this reachable* (2xx, or 401/403 labeled credential-gated). It does not answer *is
this the dataset it claims to be, and does its response have the shape the fetch code will parse*.
The Dataset Finder's external rows therefore reach the user marked `verified ✓` on evidence
thinner than the word implies.

**D4 — the hosted native tool is not used where it exists.** On a real OpenAI endpoint,
`{"type": "web_search"}` on the Responses API is a better search than any `CURIO_SEARCH_URL`
template, and it is free of the provider-key question. Curio never asks whether the configured
endpoint has it.

### Expected behavior

- **R1** On the `openai_compatible` path, granted read tools are advertised as OpenAI functions,
  `tool_calls` are executed through the SAME internal contracts, and the result is fed back — with
  the fenced protocol still accepted, because a model that ignores `tools=` must keep working.
- **R2** Web search is reachable while resolving a node: the Dataset Finder and the Node Builder
  hold `web.search`/`web.fetch`, and a tool-less content child gets runtime-gathered results as
  INPUTS when its source is unverified (`DEC-046`/`DEC-063`, the dev/95 shape).
- **R3** The Dataset Finder validates an external dataset connection rather than merely reaching
  it: the endpoint is fetched (bounded), its content type and shape are recorded, and the row says
  what was actually observed — including *"reachable but not the data it claims"*.
- **R4** Where the configured endpoint offers native web search, it is used, and the choice is
  recorded per run; where it does not, the function-calling loop with the configured provider is.
  Neither is guessed: the capability is **probed per endpoint, never tabulated by model name**.
- **R5** Every outbound call still goes through the one `DEC-053` chokepoint with its budget, and
  no key ever reaches a prompt.

---

## 2. Scope

**In scope.** `app/agents/providers.py` (advertise tools, read `tool_calls`, one capability probe
per endpoint, the Responses-API branch); `app/agents/services.py` (accept `tool_calls` as an
equivalent of the fenced request in the one loop that already executes them); `app/agents/tools.py`
(the OpenAI function schema derived FROM the existing `ToolContract`s — one source);
`app/agents/verify.py` (connection validation beyond reachability: content type, JSON shape, a
row/feature count when cheap); `builtin.py` (the Dataset Finder and Node Builder gain the web
contracts; the discovery instruction gains the search-then-validate procedure);
`app/agents/services.py`'s source-resolution path (runtime-gathered search results for a
tool-less content child when its source is unverified); docs + ledgers; tests throughout.

**Out of scope.** Retiring the fenced protocol (it is the floor that makes weak local models
work, and dev/93/94/105 exist because of it). Granting `web.fetch` to a content-writing child
(`DEC-046`). A crawler, a scraper, or anything that follows links beyond the policy's redirect
bound. Paid provider defaults: `CURIO_SEARCH_URL` stays operator-configured, with SerpAPI as the
documented no-server recommendation and SearXNG as the self-hosted one.

---

## 3. Recommended Implementation Approach

### A. One tool table, two wire formats

`tools.openai_function_schemas(granted)` derives the OpenAI `tools=[…]` array from the existing
`ToolContract`s — id, description and a per-contract `parameters` JSON Schema — so a tool cannot
exist in one protocol and not the other. `run_chat_completion` gains `tools=` / `tool_choice=`
pass-through on the `openai_compatible` branch, returns the assistant message rather than only its
text, and the loop in `services.py` treats a `tool_calls` entry exactly as it treats a parsed
fenced `toolRequest`: same grant check, same executor, same budget, same proposal minting for a
mutate contract (`DEC-006` — a native call can no more write than a fenced one). The reply the
loop feeds back is the OpenAI `role: "tool"` message when the model asked that way, and the
existing synthetic text when it asked in a fence.

### B. Capability, probed

`providers.endpoint_capabilities(config)` answers `{functionCalling: bool, nativeWebSearch: bool}`
by ASKING the endpoint (a minimal request with a one-tool array; a 400 naming the unsupported
parameter is a definitive answer), cached per endpoint+model for the process, never inferred from
a model name — dev/122's rule, which exists because a name is not a capability. A `false` answer
means the fence, which is today's behavior, so nothing regresses on gemma.

### C. Search where the node is solved

- The **Dataset Finder** gains `web.search` + `web.fetch`: its external lane becomes rows it
  found, each carrying what the runtime observed.
- The **Node Builder** gains `web.search`: its source ladder's rung (c) can find a candidate
  endpoint instead of waiting for one.
- A **tool-less content child** (the NCB) gets `searchResults` as an input when the node's source
  is unverified — the dev/95 shape, reusing `_delegated_search_results` — so "any agent whenever
  it sees a need" is honored without breaking `DEC-046`.

### D. Validating a connection, not just reaching one

`verify.validate_api_connection(url, *, expect=None)` extends the existing probe: the response's
status, content type, byte size, and — for JSON — whether it parses, whether it is an object or a
list, its top-level keys or first row's keys, and a row count when the payload states one. Bounded
by the same budget and body caps. A row then says *"verified ✓ — application/json, 77 rows, keys:
community, area_numbe…"* or *"reachable, but the response is an HTML sign-in page"*, which is the
difference the owner is asking for: the Dataset Finder's `verified` claim becomes about the data.

### E. The native tool where it exists

When `nativeWebSearch` is true, a search request goes through the Responses API's
`{"type": "web_search"}` and its results are normalized into the same `{title, url, snippet}` rows
`web.search` already returns, so every consumer (the two-lane card, the notes composer, the
grounding gate's evidence) is unchanged. The run records which lane served it.

---

## 4. Data, UI, edge cases, tests, acceptance

The sections below follow the standard and are written against the pieces above.

**Data/state.** No new persisted state: the capability cache is per process, search results are
run-scoped evidence (already bounded), and the verification verdict rides the candidate row as it
does now. Keys stay in the provider config and the connection-key store; a search provider's key
lives in `CURIO_SEARCH_URL`'s template and is redacted from every record (the `dev/116` redactor).

**UI.** The candidates card's verification chip gains the observed detail (content type, row
count, keys) behind its existing tooltip; the run's tool line names `web.search` as it already
does for the Researcher. No new surface.

**Edge cases.** No search provider configured (honest *not configured*, and the Dataset Finder
says so rather than inventing rows); an endpoint that supports `tools=` but returns malformed
`tool_calls` (fall back to the fence, record it); a model that emits BOTH a fence and a tool call
(the tool call wins, once); a search result set that is empty (a row-less lane, stated); a
non-public host (refused by the egress policy, as now); an endpoint whose JSON is 200 MB (the body
cap ends it and the row says so); native web search available but rate-limited (the error is the
row's evidence); `tool_choice` unsupported (drop it, keep `tools`).

**Tests.** The schema derivation from contracts; the capability probe's three answers with a
cached second call; a native `tool_calls` round executed through the same executor as a fence, and
a mutate call minting a review rather than executing; the fence path byte-unchanged when the probe
says no function calling; the Dataset Finder's lane built from real search rows; the connection
validator's shapes (JSON object, JSON list, HTML sign-in, 401, oversized); the runtime-gathered
inputs for a tool-less child; and one end-to-end route test where a data-loading node's source is
found by search, validated, confirmed, and the loader written.

**Acceptance.** (1) A function-calling endpoint receives the granted tools and its `tool_calls`
execute through the existing contracts, budget and review rules. (2) A fence-only endpoint behaves
exactly as today. (3) The Dataset Finder searches, and every external row states what the runtime
observed about the connection. (4) A tool-less content child receives search results as inputs
when its source is unverified. (5) Native web search is used where the endpoint has it, chosen by
probe and recorded. (6) No key appears in any prompt, record or card. (7) Suites green.

---

## 5. Recommended commit breakdown

1. `openai_function_schemas` derived from the contracts + tests.
2. The capability probe (`endpoint_capabilities`) + tests.
3. `tools=`/`tool_calls` on the provider path and in the one tool loop, fence unchanged + tests.
4. `validate_api_connection` + the richer verification verdict on candidate rows + tests.
5. Grants and instructions: Dataset Finder (+ the search-then-validate procedure), Node Builder,
   and the runtime-gathered inputs for the tool-less child + tests.
6. The Responses-API native branch + tests.
7. Docs + ledgers.

## 6. Open questions

- **F1** Which endpoints in the owner's deployment actually support function calling — the probe
  answers it per endpoint, but the answer is worth recording in the memo once measured on
  `sage200` (gemma) and on an OpenAI key.
- **F2** Whether a validated connection should be re-validated at Solve time (the endpoint may
  have changed since the card was minted). The grounding gate already re-probes; the richer
  validation could ride the same call.
- **F3** Whether `web.search` should count against the same four-call budget as `web.fetch` when a
  search is what unblocks a node — the owner's "as many retries as possible" pressure applies here
  too, and the budget is per run.
