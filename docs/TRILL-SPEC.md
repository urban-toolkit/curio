# The Trill dataflow specification

A Curio dataflow is saved as a single JSON document called a **trill**. This page
describes that format. Every trill is validated against
[`docs/schemas/trill.v1.json`](schemas/trill.v1.json) (JSON Schema Draft 2020-12),
and the schema is the source of truth for what fields a dataflow can carry.

Trills live in two places:

| Where | What |
|---|---|
| `.curio/users/<userKey>/projects/<projectId>/spec.trill.json` | a user's saved projects |
| `docs/examples/*.json`, `docs/examples/dataflows/*.json` | the examples shipped in-repo |

## Structure

```
spec
├── dataflow                    required
│   ├── nodes[]                 required - the boxes on the canvas
│   ├── edges[]                 required - the wires between them
│   ├── name, task,             required - always written by the canvas
│   │   timestamp,
│   │   provenance_id
│   ├── packages[]              node-package lockfile      (backend-owned on update)
│   ├── datasets[]              Data Catalog references    (backend-owned on update)
│   ├── description
│   ├── agents[]                agent lockfile             (backend-owned, stripped on share)
│   ├── agentAttachments[]      live agent bindings        (backend-owned, stripped on share)
│   └── agentDefaults           deprecated
├── nodeProvenance              per-node execution history (browser-side only)
├── dataflowProvenance          version history of the whole dataflow
└── name                        deprecated top-level alias
```

### A node

`id`, `type`, `x` and `y` are required. Everything else is optional, including
`in`, `out`, `goal` and `metadata`: the agent apply path writes
`{id, type, content, goal, x, y}` and nothing more.

`content` holds the node's payload: Python or JavaScript source, or a grammar
document. It is absent on presentation-only templates. `title` and
`metadata.appearance` support post-it style notes; `appearance.backgroundColor`
accepts a palette name *or* a `#rrggbb` value, because agents are instructed to
supply either.

`metadata.comments` carries the node's discussion, written only when non-empty.
Each entry is `{id, text, author, authorName, createdAt, resolved}`. The author's
avatar is not stored, because `profile_image` may be a full data URL; `canDelete`
is not stored either, because it is derived on read by comparing `author` to the
current user.

### An edge

`id`, `source` and `target` are required. `type` is present only on an interaction
edge, where its single legal value is `"Interaction"`; absence means a plain data
edge. There is no `"Data"` value.

`sourceHandle` and `targetHandle` name the concrete ports. They matter: when they
are absent, the reader infers a merge slot from an `in_N` substring of `edge.id`,
which cannot recover a named port such as `in_points`.

### Ownership

Three sections are **backend-owned on update** — the server overwrites whatever a
client sends, so a stale browser tab cannot clobber them: `packages`, `datasets`,
and the agent sections. Two are additionally **stripped on share**: `agents` and
`agentAttachments` are removed from the copy served behind a share link, so a
shared dataflow never carries them and they can never be required.

## What lives in the manifest, not here

**Nodes are defined by package manifests.** A node's `type` is a coordinate —
`<packageId>/<templateId>` or `…@<major>` — into a manifest's `templates[].id`,
and `dataflow.packages` is the lockfile naming which manifests must be installed
for those coordinates to resolve. The trill schema validates the *shape* of that
coordinate and stops there.

Everything a template decides is therefore out of scope here, because it depends
on which packages are installed:

| Constraint | Lives in |
|---|---|
| Whether a `node.type` exists at all | `templates[].id` |
| Which `targetHandle` ids are legal | `template.inputPorts` |
| Whether `node.in`/`out` are *compatible* | `port.types`, `port.cardinality` |
| Whether a node has code at all | `template.editor` (`none` means it does not) |
| Whether an interaction edge is legal | `template.bidirectional` |
| What language `content` is written in | `template.engine` |

See [`docs/NODE-CATALOG.md`](NODE-CATALOG.md) and
[`docs/schemas/node-package.v4.json`](schemas/node-package.v4.json). Two details
where the two schemas nearly agree:

- The **port-type enums differ by exactly one value**. A manifest port declares a
  *capability* and lists the six `SupportedType` members; `node.in` and `node.out`
  record *what a node is currently set to* and add `DEFAULT`.
- `node.type`'s template half uses the same grammar as `templates[].id`. A test
  asserts they stay equal, since the two schemas version separately.

The trill schema does **not** enum `node.type`, because packages are
user-installable.

## Checking a dataflow

```bash
python scripts/validate_trill.py docs/examples/           # a file or a directory
python scripts/validate_trill.py --all                    # every corpus, including .curio
python scripts/validate_trill.py --all --resolve          # also check types resolve
```

`--resolve` adds the manifest check the schema cannot do: every node type must
correspond to a template under `packages/`.

## Laying a dataflow out

The schema says nothing about where a node sits, so a spec can be perfectly valid
and still draw its boxes on top of each other. That is a layout question, and it
has its own tool:

```bash
python scripts/tidy_example_layout.py --all            # check, exit 1 on drift
python scripts/tidy_example_layout.py --all --write    # apply
```

It rewrites nothing but `x` and `y` on `dataflow.nodes[]`, and it refuses a file
it cannot reproduce byte-for-byte rather than reformatting it. Scope is the
curated gallery examples only — `docs/examples/dataflows/` is hand-tuned fixture
material and `.curio/` is your own work.

CI validates the committed examples on every push. It cannot see your own
projects, since `.curio/` is gitignored, which is what the CLI is for.

### Your saved projects may report failures

Projects saved before the schema existed may be missing `provenance_id`,
`timestamp`, `name` or `task`. A non-zero exit from `--all` on those is
information, not a broken build; fix them with the one-time rewrite
[`docs/NODE-CATALOG.md`](NODE-CATALOG.md) describes.

A missing `name` has a visible symptom: `dataflowProvenance.latest`
interpolates the name into its version keys, so a spec saved without one carries
keys that literally read `undefined_1787609706100`.

Snapshots inside `dataflowProvenance.versions` are held to a **relaxed** version
of the same shape, requiring only `nodes` and `edges`.

## Known drift

- **`llm-prompts/default_preamble.txt` embeds a stale Draft-07 schema** and sends
  it to the model on every AI call. It declares `timestamp` as a string, node
  types as a dead uppercase enum (`DATA_LOADING`), and three fields nothing reads
  (`node.output`, `metadata.annotations`, edge type `"Data"`), while omitting
  everything added since: `title`, the `dashboard*` family, `saveOutputDataset`,
  `metadata.appearance`, the handles, and all of `packages`, `datasets`, `agents`
  and `agentAttachments`. Until it is rewritten, LLM-generated specs will not
  validate against this schema.
- **Two name conventions coexist.** `dataflow.name` is authoritative, but
  `execution/workflow_spec.py` still reads a top-level `name`. Both are valid; a
  top-level one *without* a `dataflow.name` is the footgun documented in
  `backend/tests/test_frontend/README.md`.
