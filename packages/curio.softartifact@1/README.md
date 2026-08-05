# Soft Artifact (curio.softartifact@1)

A Curio node that puts a *document* on the canvas — a PDF, plain-text file, markdown file, or meeting transcript — and uses an LLM to turn its content into workflow help.

**One node = one document. The node's *role* chooses what the LLM does with that document.**

| Role | What it does |
|---|---|
| `inform` | Guidance on the *next* node to add, plus 1–3 suggested nodes with citations |
| `explain` | Cited plain-language narration of what the dataflow does (or should do) to operationalize the document |
| `transform` | Proposes a full replacement dataflow that operationalizes the document, grounded in the current canvas |
| `expand` | Proposes a new / branched dataflow (what-if scenarios, alternative data sources, comparisons) |

Every LLM answer is grounded in retrieved passages from the document and cites them by chunk (`[1]`, `[2]`, …), so claims can be traced back to a PDF page or a transcript timestamp.

## Using the node

1. Drop a **Soft Artifact** node on the canvas (category: *data*).
2. Pick a role from the dropdown (`inform` / `explain` / `transform` / `expand`).
3. Choose a file (`.pdf`, `.txt`, `.md` — transcripts are auto-detected inside `.txt`) and click the ingest button.
4. The node uploads the file, the backend chunks and stores it, and the role's LLM flow runs automatically.
5. Results render inside the node:
   - `explain` → the narration text
   - `inform` → guidance text + a suggestions JSON block
   - `transform` / `expand` → a rationale plus **Apply proposal** / **Cancel** buttons; *Apply* loads the proposed Trill onto the canvas
6. The ingested chunks are listed in the node (labeled `page N` for PDFs, `speaker @ HH:MM:SS` for transcripts) so you can see exactly what the LLM was given.

The node also emits its result as a `JSON` output port, so you can wire it into a downstream node (e.g. Simple View) to inspect the raw descriptor, spans, and LLM output.

Auth: `retrieve`, `explain`, `inform`, and `propose_trill` require login (same session-token pattern as Curio's other LLM routes). `ingest`, `health`, and the artifact-metadata lookups do not.

## Architecture

The feature spans four layers:

### 1. Node package (`packages/curio.softartifact@1`)

- Registers the **Soft Artifact** template via Curio's package system (`manifest.json`, behavior id `soft-artifact`).
- All UI + behavior live in `sources/softArtifactBehavior.tsx`; it talks only to `/api/softartifact/*`.
- Persists its own state on the node as `data.softArtifact` (artifact id, role, status, cached results, chunks) so the UI survives refresh and reload.
- On mount, re-verifies a previously saved `artifact_id` against the backend; if the artifact is gone, the node resets and asks for a re-upload.
- Built by `webpack.packages.config.js` into `scripts/behaviors.js`, like the other node packages.

### 2. Backend blueprint (`utk_curio/backend/app/softartifact`)

A Flask blueprint mounted at `/api/softartifact`:

| Endpoint | Job |
|---|---|
| `POST /ingest` | Accept file → uuid → chunk → store (DuckDB + on-disk copy) |
| `GET /artifacts/<id>` | Metadata lookup (used to re-verify after a page refresh) |
| `GET /artifacts/<id>/chunks` | All stored chunks for an artifact (shown in the node UI) |
| `POST /retrieve` | Score chunks vs. a query → top-k spans |
| `POST /explain` | retrieve → LLM narration with citations |
| `POST /inform` | retrieve → LLM guidance + suggested next nodes (JSON) |
| `POST /propose_trill` | chunks + current Trill + node-type registry → LLM dataflow proposal |
| `GET /health` | Liveness probe polled by the node UI (every 60 s) |

Services layout:

```
softartifact/
├── routes.py                  # endpoint wiring + validation
└── services/
    ├── ingest.py              # file-type detection, chunking (pdf / text / transcript)
    ├── explain.py             # explain flow (also shares helpers with inform/propose)
    ├── inform.py              # inform flow, parses the LLM's JSON suggestions
    ├── propose.py             # transform/expand flow, builds + parses Trill proposals
    └── LLM_helper/
        ├── chunk_schema.py    # frozen Chunk dataclass (pdf_page | text | transcript_turn)
        ├── store.py           # DuckDB persistence (softartifacts + chunks tables)
        ├── retrieve.py        # TF-IDF + cosine-similarity ranking (nltk + scikit-learn)
        └── get_artifact.py    # artifact-id validation + metadata lookup
```

LLM access reuses Curio's existing helpers (`_resolve_llm_config`, `_call_llm`) from `app/api/routes.py`, so the node works with whatever provider/model the deployment is already configured for.

### 3. Host workflow glue (`utk_curio/frontend/urban-workflows`)

Soft Artifact is not fully self-contained for transform/expand — the host injects three callbacks into every node's data (`useCode.ts`, typed in `registry/types.ts`):

| Callback | Purpose |
|---|---|
| `getCurrentTrill()` | Snapshot of the live canvas as Trill JSON, passed to the LLM as context |
| `applyProposal(dataflow)` | Load a returned Trill proposal onto the canvas (and install any missing package deps) |
| `cancelProposal()` | Discard the proposal and clear workflow-suggestion UI state |

Persistence across save/reload:

- `TrillGenerator` writes `data.softArtifact` into the Trill node's `metadata` on save.
- `useCode.loadTrill` restores `metadata.softArtifact` back onto the node when a Trill is loaded.

### 4. Prompts (`utk_curio/llm-prompts/`)

One system-prompt file per role: `softartifact_explain_prompt.txt`, `softartifact_inform_prompt.txt`, `softartifact_transform_prompt.txt`, `softartifact_expand_prompt.txt`. The transform/expand prompts embed the node-type registry (legal `type` strings with their in/out data types) and strict JSON output rules so proposals are runnable Trill graphs, not pseudo-code.

## Ingestion and chunking

`ingest.py` picks a chunker from the file type:

- **PDF** — text is extracted per page with `pypdf` and split into ~500-character chunks; each chunk keeps its 1-based page number (`kind: pdf_page`).
- **Transcript** (auto-detected inside `.txt` by regex profiling) — two formats are recognized:
  - `A`: `[Speaker Name] HH:MM:SS` header lines followed by the utterance
  - `B`: `HH:MM:SS caption text` per line
  Consecutive turns by the same speaker within 25 s are merged (capped at ~2000 chars) into `transcript_turn` chunks carrying `speaker`, `t_start`, `t_end`.
- **Plain text / markdown** — fixed-size 500-character chunks with `char_start` / `char_end` offsets (`kind: text`).

Chunks are validated by the frozen `Chunk` dataclass (a `pdf_page` chunk must carry a page, a `transcript_turn` chunk must carry speaker + times, etc.).

## Storage and retrieval

- **DuckDB** at `.curio/data/softartifacts.duckdb` holds two tables: `softartifacts` (artifact metadata) and `chunks` (one row per chunk, keyed by `artifact_id + chunk_id`).
- The raw upload is also copied to `.curio/data/softartifacts/<artifact_id>/<filename>`, alongside a `chunk.json` debug dump.
- **Retrieval** (`retrieve.py`) ranks chunks against a query with TF-IDF vectors + cosine similarity (nltk tokenization), returning the top-k spans with scores. `explain` and `inform` use retrieval with role-specific default queries; `transform`/`expand` currently send *all* chunks (RAG bypassed) so the proposal sees the whole document.

## Data flow by role

**Ingest (all roles)**
file → `POST /ingest` → `{ artifact_id, sourceFile, mimetype, kind, status }` → saved on the node → emitted as JSON output → chunks fetched and listed in the UI

**Explain**
artifact_id + current Trill → retrieve spans → LLM → cited `explanation` (cached on the node so it survives refresh)

**Inform**
artifact_id + current Trill → retrieve spans → LLM → `guidance` + `suggestions { subtask, recommendedNodes[] }`

**Transform / Expand**
artifact_id + `getCurrentTrill()` + node-type registry → `POST /propose_trill` → `{ proposal: { dataflow }, rationale }` → user reviews → **Apply** (loads onto canvas) or **Cancel**

## Current limitations (v1)

- Chunking is size-based (~500 chars) rather than semantic; retrieval is TF-IDF, not embeddings.
- `role` is accepted at ingest but not persisted server-side; the node owns role state.
- Transform/expand skip retrieval and send every chunk, so very large documents may exceed the model's context.
- Supported inputs are `.pdf`, `.txt`, `.md` only; scanned (image-only) PDFs yield empty text.
- Proposals are applied as a full canvas replacement (never a delta), by design of the transform prompt.