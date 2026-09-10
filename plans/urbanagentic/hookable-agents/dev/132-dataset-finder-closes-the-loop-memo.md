# dev/132 — The Dataset Finder closes its own loop: delegate the fetch automatically, or teach the manual download with an Import button, then hand the just-imported dataset to the builders

**Status: IMPLEMENTED (2026-09-10) on `imp/agentcatalog` — `BL-P5-20260910-67`, and **no new
`DEC`**: `DEC-047`'s hand-off keeps its review gate (the delegation produces the same reviewed
content Solve already produces) and `DEC-053`'s "the runtime records the verdict" is what the
access classification IS. Commits `653fa934` (the access verdict + the steps), `25c6a409` (the
automatic delegation), `f3f2eca3` (the card, the shared Import, the imported dataset as the
source), `48108ff3` (dev/131 F4), and this docs commit. Every line number below was read on
`61ec9013`.**

Date: 2026-09-10
Branch / tree: `imp/agentcatalog` @ `61ec9013` (dev/131's tracking commit).
Origin: owner instruction — *"The datafinder should be able to automatically delegate the code to
fetch external api datasets, if it must be downloaded manually, it should include the steps to
download in the portal and an import button (the same data catalog import) to properly include the
dataset into the data catalog. Once it is uploaded, the dataset finder should properly delegate the
solving to the node builder or content builder using the just-uploaded dataset."*
Family: dev/50 (the Dataset Finder's two lanes) → dev/67-4 (`DEC-053`, the runtime's verification
verdict) → `DEC-047` (the user-mediated hand-off to Node Builder) → dev/114 (`DEC-072`, source
grounding; the runtime-minted candidates card) → dev/126 (`DEC-080`, the Finder attached to the
data-loading node; the recorded selection) → dev/128/129 (the input contract; validated before
written) → dev/131 (the session that keeps managing) → **dev/132 (this memo)**.
Design decisions consumed: `DEC-047`, `DEC-072`, `DEC-080`, `DEC-006` (nothing mutates without
review), `DEC-063`, `DEC-053`.

---

## 1. Problem Statement

Three gaps, all at the seam between *finding* a source and *having working code*.

**D1 — the external hand-off is manual by construction.** `DEC-047` made the Finder's external
lane a *suggested prompt*: the card composes *"Ask Node Builder: author a fetch node for … "*
(`discovery_instruction.txt:16`) and the user sends it. dev/126 added the recorded selection, so
the runtime already knows the confirmed row — and still nobody hands it to a builder. The owner's
instruction is that this delegation happen **automatically** once a source is confirmed.

**D2 — a portal download has no path at all.** Many public datasets are not an API: the portal
requires a browser download (a click-through, a captcha, an accept-terms page). Today such a row
can only be described. Nothing tells the user *how* to get the file, and nothing brings the file
into Curio from that card — even though **the import already exists**: `POST /datasets/import`
(`datasets/routes.py:155`-`:169`) plus `useDatasetImport` (`services/datasetCatalog/useDatasetImport.ts`),
the ONE import pathway shared by the drawer footer and the catalog page, register-only and
dataflow-free by design.

**D3 — after an import, nothing continues.** The imported dataset lands in the catalog with an id,
and the node that needed it stays pending: the Finder does not notice, and dev/131's session sees
no change to that node's dataset-selection record (its blocker signature is unmoved), so it waits
until its budget runs out.

### Expected behavior

- **R1** A confirmed EXTERNAL API row delegates the fetch automatically: the node's own Node
  Builder is asked, with the verified URL, the observed response shape and the connection-key
  requirement, and the result arrives as the ordinary reviewed content — no prompt the user must
  compose.
- **R2** A row that cannot be fetched programmatically carries **download steps** (portal URL,
  what to click, what file to expect, its format and licence note when the row states one) and an
  **Import** button that runs the same catalog import as everywhere else.
- **R3** After the import, the just-imported dataset becomes the node's recorded source, and the
  Finder delegates solving to the Node Builder / Content Builder **with that dataset id** — the
  loader is written against `curio_dataset_path("<id>")`, and dev/131's session picks the node up
  because its record moved.
- **R4** Every claim stays evidence-based: *"downloadable, not fetchable"* is a verdict the runtime
  recorded (a portal page, a 403 on the data URL, a `text/html` response), never a guess, and the
  steps are the row's own metadata rather than invented instructions.
- **R5** Nothing mutates without review (`DEC-006`): the automatic delegation produces a reviewed
  content proposal (or, for an empty plan node, the same written-on-pass path Solve already uses),
  and the import is the user's own click.

---

## 2. Scope

**In scope.**
- `app/agents/verify.py` / dev/130's `validate_api_connection`: classify a confirmed row as
  `fetchable` (a data response the code can parse) or `manual-download` (an HTML portal, a 403 on
  the data URL, a login page), recorded on the row.
- `app/agents/dataset_resolution.py`: on `record_selection`, when a pick is `fetchable`, trigger the
  **automatic delegation** (the node's Node Builder, `node.build`/`node.content.generate` with the
  confirmed source); when it is `manual-download`, record the steps and leave the node awaiting the
  import.
- `app/agents/services.py`: the delegation seam (reuse `_run_delegate_traced` + the existing
  content-review mint) and a hook so an import that names a node continues its resolution.
- `app/datasets/*`: no new import path — the existing route is reused; the agent side needs only
  the resulting dataset id (already returned).
- `content.py`: the candidate row gains `access` (`fetchable` | `manual-download` | `unknown`) and
  `downloadSteps` (bounded, plain text), both runtime-minted.
- Frontend: the candidates card renders the steps and an **Import dataset** button wired to
  `useDatasetImport` (the same pathway, same toast, same refresh fan-out), then posts the resulting
  dataset id to the selection endpoint so the record names it.
- `discovery_instruction.txt`: the Finder stops composing hand-off prompts for a confirmed row and
  states the two lanes it now has (delegated fetch, or download-and-import).
- Docs + ledgers + tests.

**Out of scope.** Automating the download itself (a click-through portal is a browser task, and
scripting one is both brittle and often against terms — the memo says so plainly rather than
pretending). Any second import pathway. Changing `DEC-006`'s review gate. Credential capture (the
dev/116 connection-key flow is what a keyed API already uses).

---

## 3. Recommended Implementation Approach

### A. One verdict, three answers

`verify.classify_access(url, observation)` turns what dev/130's validator already observed into
`fetchable`, `manual-download` or `unknown`:

- JSON/CSV/GeoJSON body, 2xx → `fetchable`;
- `text/html` at the data URL, or a 403/401 with a portal-shaped body → `manual-download`;
- anything else → `unknown`, and the row says so.

The verdict rides the candidate row, so the card can offer the right thing and the session can
record the right blocker.

### B. Automatic delegation for a fetchable pick

`dataset_resolution.record_selection` already writes the confirmed rows. When at least one is
`fetchable`, it now also **delegates**: the node's own Node Builder is asked for the loader with
`confirmedSource` (dev/129's input), the observed shape, and the connection-key line when the host
has a saved key (dev/116). The reply travels the ordinary route — the reviewed
`node.content.write` mint for a node with content, the written-on-pass path for an empty plan node
— so `DEC-006` is untouched and the user still sees what landed. dev/131's session then finds the
node's record `resolved` and its content present, and moves on.

### C. Download steps and the Import button for a manual pick

The row carries `downloadSteps`: the portal URL, the click path the Finder observed or the row's
own metadata states, the expected file name/format, and any licence note — bounded, plain text,
and explicitly *"as the portal describes it"* rather than invented. The card renders them as an
ordered list with an **Import dataset** button that runs `useDatasetImport` — the same register-only
import as the drawer footer and the catalog page, with the same refresh fan-out (the palette
provider and the dropdown hold separate caches). On success the card posts
`{picks: [{lane: "catalog", key: "<new dataset id>"}]}` to dev/126's selection endpoint, so the
node's record becomes a **catalog** source naming the imported dataset.

### D. Continuing after the import

Because the selection record moved, dev/131's blocker signature for that node changes and the
running session attempts it on its next pass — the loader is written against
`curio_dataset_path("<id>")`, which dev/114's grounding gate accepts by id. When no session is
running, the same record makes the next Solve (or the node's own per-pill Solve, dev/131) resolve
it. And dev/131's **F4** matters here: a dataset imported mid-session has no sandbox path inside
the running job, so this memo either closes F4 (a path resolver that needs no request context) or
states that the node resolves on the next Solve. **Closing F4 is in scope** — the import gives us a
dataset id, and resolving one id to a path is exactly what `_resolve_catalog_execution_paths` does;
it needs the acting user, which the job can hold from its start.

---

## 4. Data, UI, edge cases, tests, acceptance

**Data.** The row's `access`/`downloadSteps` are runtime-minted parts of the existing
`datasetCandidates` payload (bounded, plain text). The selection record gains nothing new — an
imported dataset is an ordinary catalog pick. The import writes through the existing catalog
service; no agent writes a dataset.

**UI.** Under a `manual-download` row: an ordered list of steps, the portal link (plain, opened by
the user), and **Import dataset** beside it, disabled while an import is in flight, with the same
toast the other two surfaces show. A `fetchable` row shows *"the fetch is being written"* once the
delegation starts, and the reviewed content arrives in the node's own chat.

**Edge cases.** A portal whose page moves (the steps are stated as observed, with the URL, and go
stale honestly); an import that registers several datasets (an OSM PBF registers one per layer —
the card asks which layer the node needs rather than guessing); an import the user cancels
(nothing recorded); a `fetchable` row whose fetch later fails (dev/127's trail and dev/131's
session handle it as any failure); a row that is both (an API AND a bulk download — `fetchable`
wins and the steps stay available); a keyed API (dev/116's flow, unchanged); an import while a
session runs (§3D / dev/131 F4).

**Tests.** `classify_access`'s three answers over recorded observations; `record_selection`
delegating exactly once for a fetchable pick and not at all for a manual one; the steps' bounds
and their "as observed" framing; the card rendering steps + Import, calling the shared import hook,
and posting the new dataset id as a catalog pick; the node resolving on the next pass with
`curio_dataset_path("<id>")` in the written loader; F4's path resolution inside a running session.

**Acceptance.** (1) A confirmed API row produces reviewed loader code with no prompt composed by
the user. (2) A manual row shows steps and an Import button that uses the existing pathway. (3) An
imported dataset becomes the node's source and the node resolves without the user explaining
anything further. (4) Every verdict and every step is traceable to an observation or to the row's
own metadata. (5) No new import path, no bypassed review, no scripted portal download.

## 5. Commit breakdown

1. `classify_access` + the row's `access`/`downloadSteps` (+ tests).
2. Automatic delegation on a fetchable confirmation (+ tests).
3. The card: steps, Import (shared hook), and posting the imported id (+ jest).
4. Continuing after the import, including dev/131 F4's path resolution (+ tests).
5. The Finder's instruction, docs, ledgers.

## 6. Open questions

- **F1** Which portals in the owner's work are click-through (Brás/IBGE/SEADE/GeoSampa were in
  `224d23a2`)? The steps' usefulness depends on the row metadata those portals expose; worth
  measuring on the first real run.
- **F2** Should a `manual-download` row be allowed to become `fetchable` after a Researcher search
  finds a direct data URL (dev/130's web search)? Probably yes, and it belongs there.
- **F3** An OSM PBF import fans out to one dataset per layer; the card must ask which layer the node
  needs. Bounded UI question, worth its own small design.

---

## 7. What changed while building

1. **dev/130 was NOT needed first.** §2 named dev/130's `validate_api_connection` as the source of
   the access verdict; it turned out dev/67-4's probe already observes everything the split needs
   (content type, HTTP status, the page title of a non-data answer), so `classify_access` is a pure
   function of one existing observation and dev/130 stays independent. Nothing here waits on it.
2. **The delegation is the per-node Solve, not a new lane.** The memo said "the node's Node Builder
   is asked… and the result arrives as the ordinary reviewed content"; the honest way to get all of
   that — grounding, the recorded source, the input contract, document and execution verification,
   `DEC-006`'s review for a node that already has content — is to start the SAME detached per-node
   Solve the user's own button starts. So the endpoint starts that job and reports what it did:
   `delegating`, `session-running` (dev/131's session owns the node; two builders would race for its
   content), `manual-download`, `no-builder` or `skipped` with the reason.
3. **An imported dataset resolves the node instead of waiting for an install.** dev/126 routes a
   not-installed catalog pick to `awaiting-install`, which for a file the user has just imported
   would be a second, unexplained step. A pick the user brought in themselves after the card was
   minted is marked `imported` and resolves: its file is in their own account store and
   `curio_dataset_path("<id>")` resolves it. The reviewed install lane adds a dataset to the
   DATAFLOW — a separate act, not what reading the file needs. Card-listed uninstalled rows keep
   dev/126's rule exactly.
4. **`resolve_picks` grew a second grounding source, deliberately.** The card is older than the
   imported file, so an unmatched CATALOG key is resolved against the runtime's own Data Catalog
   listing (the same one `catalog.search` serves and `DEC-072` grounds against, read in the request
   context). The client still sends identifiers only, and a key the catalog does not have is still
   a 422 — the rule "a selection cannot introduce a source the runtime never saw" holds.
5. **The provider's toast had to become optional.** The shared import reports through
   `useToastContext`, which throws outside a `ToastProvider` — and the attachments provider is
   rendered bare in 47 of its own tests. `useOptionalToastContext` is the narrow addition.
6. **dev/131 F4 is closed here** (§3D's option): the acting user is captured at both Solve entry
   points and the path mapping is topped up lazily for an id the eager pass never saw.

Not done, and not in scope: automating a portal download (§2 said so and it stands), a second
import pathway, and dev/130's web search (F2 — a Researcher search that finds a direct data URL
could turn a `manual-download` row `fetchable`, and belongs there).
