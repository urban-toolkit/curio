
One node = one document. Role chooses what the LLM does with that document.

---

## Layers

### 1. Node package (`packages/curio.softartifact@1`)

- Registers the **Soft Artifact** template in Curio’s package system
- UI + behavior live in `softArtifactBehavior.tsx`
- Talks only to `/api/softartifact/*`
- Persists its own state on the node as `data.softArtifact`

**Roles**

| Role | Meaning |
|---|---|
| `inform` | Guidance + suggested next nodes |
| `explain` | Cited summary of the doc |
| `transform` | Propose edits to the current dataflow |
| `expand` | Propose a new / branched dataflow |

### 2. Backend (`utk_curio/backend/app/softartifact`)

Mounted at `/api/softartifact`.

| Endpoint | Job |
|---|---|
| `POST /ingest` | Accept file → uuid → chunk store |
| `GET /artifacts/<id>` | Metadata lookup (used after refresh) |
| `POST /retrieve` | Score chunks vs query → top-k |
| `POST /explain` | retrieve → LLM summary |
| `POST /inform` | retrieve → LLM guidance/suggestions |
| `POST /propose_trill` | retrieve → LLM dataflow proposal |
| `GET /health` | Liveness for the node UI |

Auth: retrieve / explain / inform / propose require login (same pattern as other LLM routes).

### 3. Host workflow glue (urban-workflows)

Soft Artifact is not fully self-contained for transform/expand. The host injects three callbacks into node data:

| Callback | Purpose |
|---|---|
| `getCurrentTrill()` | Snapshot of current dataflow as LLM context |
| `applyProposal(dataflow)` | Apply returned Trill onto the canvas |
| `cancelProposal()` | Discard proposal UI state |

Persistence across save/reload:

- `TrillGenerator` writes `softArtifact` into Trill `metadata`
- `useCode` restores it when loading a Trill

### 4. Prompts (`utk_curio/llm-prompts/`)

One prompt file per LLM role: explain, inform, transform, expand.

---

## Data flow by role

**Ingest (all roles)**  
file → `/ingest` → `{ artifactId, sourceFile, mimeType, ... }` → saved on node → emitted as JSON output

**Explain**  
artifactId → retrieve spans → LLM → `explanation` (cached on node so it survives refresh)

**Inform**  
artifactId → retrieve spans → LLM → `guidance` + `suggestions`

**Transform / Expand**  
artifactId + `getCurrentTrill()` → `/propose_trill` → `proposal` + `rationale` → user Apply/Cancel

---

## Storage shape
.curio/data/softartifacts/ / chunk.json # chunked text used by retrieve ...metadata...

