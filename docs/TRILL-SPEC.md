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
│   ├── categories              tags, city, topic, complexity set by hand
│   ├── scenarios[]             named selections of the nodes
│   ├── agents[]                agent lockfile             (backend-owned, stripped on share)
│   └── agentAttachments[]      live agent bindings        (backend-owned, stripped on share)
├── nodeProvenance              per-node execution history (browser-side only)
└── dataflowProvenance          version history of the whole dataflow
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

`metadata.packageTemplateLabel` is the node's header when the user has renamed
it. It is written only when non-blank; without it the header shows the
template's label.

`metadata.packageTemplateConfig` is what the node settings modal saved for the
node: its title, description, editor mode, engine, which editor tabs it shows,
and its ports. It is absent until the modal saves. It does not repeat the
node's code, which is `content`, and its ports carry no ids.

`metadata.dataPool` holds a Data Pool's two conflict modes,
`{insideChart, betweenCharts}`, each `OVERWRITE`, `MERGE_AND` or `MERGE_OR`.
Only a mode other than `OVERWRITE` is written; an absent member, or an absent
`dataPool`, means `OVERWRITE`.

`metadata.widgets` lists the node's widgets, written only when it has any. Each
entry is `{name, type, label?, default, value?, options?}`, where `type` is one
of `number`, `slider`, `text`, `choice`, `checkbox`, `checkbox-group`,
`multi-select`, `datetime`, `location`, `number-list`, `text-list`, `range`
and `file`. `options.choices` lists the options of a choice, checkbox group or
multi-select widget, and `options.display` is `radio` for a choice drawn as
radio buttons. A number or slider widget takes `options.min`, `max`, `step` and
`units`; a slider needs `min` and `max`. A checkbox group or multi-select holds a
list of its choices, a datetime `YYYY-MM-DDTHH:mm:ss` in local time, and a
location `{"lat": ..., "lon": ...}` in WGS84. A widget without a `default` takes
its type's: `min` or 0 for a number or slider, `false` for a checkbox, the first
choice for a choice, `[]` for the list types, `[0, 1]` for a range,
`1970-01-01T00:00:00` for a datetime, `{"lat": 0, "lon": 0}` for a location, and
`""` otherwise. The node's
`content` places a widget as `[!! name !!]`; a run replaces it with `value` when
set, else `default`. A reference on its own becomes a literal of the code's
language (quoted text, a number, a list, a boolean, an object); one inside a string literal
becomes the value's text, escaped for that string. An old
`[!! name$TYPE$default !!]` marker, or a name the node has no widget for, fails
the run with a message naming it.

`metadata.comments` carries the node's discussion, written only when non-empty.
Each entry is `{id, text, author, authorName, createdAt, resolved}`. The author's
avatar is not stored, because `profile_image` may be a full data URL; `canDelete`
is not stored either, because it is derived on read by comparing `author` to the
current user.

### An edge

`id`, `source` and `target` are required. `type` is present only on an interaction
edge, where its single legal value is `"Interaction"`; absence means a plain data
edge. There is no `"Data"` value.

`sourceHandle` and `targetHandle` name the concrete ports. A node whose one input
port takes several edges has a circle per edge: `in` is the first, then `in_1`,
`in_2`, and so on. Its code reads circle N as `[!! input N !!]`, and the order of the
circles is the order of `arg`. When the handles are absent, the reader infers a
circle from an `in_N` suffix of `edge.id`, which cannot recover a named port such as
`in_points`.

### Categories

`categories` holds what a person said the dataflow is about, each section a list
of short labels: `tags`, `city`, `topic`, and `complexity` (one of Beginner,
Intermediate or Advanced). The Projects page filters by these, and by two things
this document does not store: where the dataflow came from (a use case, an
example or a test that ships with Curio), and the tags and data types its nodes
imply (an Autark node, `import geopandas`, a raster dataset). A save that leaves
`categories` out keeps the ones already saved.

### Scenarios

`scenarios` lists named selections of the dataflow's nodes. Each one is
`{id, name, color, description?, nodes, collapsed?, box?, source?}`:

- `id` is unique among the scenarios, `color` a hex color such as `#2a9d8f`, and
  `nodes` the ids of its nodes.
- `collapsed` and `box` say whether the canvas draws it as one box, and where.
- `source` names the project and scenario it was dragged in from.

What enters a scenario from nodes outside it is its fixed context, its nodes are
what it changes, and the outputs of its last nodes are what it produces.

A node belongs to at most one scenario: a save that puts a node in two, or gives
two scenarios one id, is refused. A save drops ids that are not nodes of the
dataflow, so deleting a node removes it from its scenario. A scenario whose last
node was deleted keeps its name and color until it is deleted itself.

The canvas writes `scenarios` on every save, and an empty list clears them. A
save that leaves the key out keeps the ones already saved, and a dataflow
without scenarios has no key. Version snapshots and an agent's view of the
dataflow carry them only when there are some.

### Ownership

Three sections are **backend-owned on update**, so the server overwrites whatever
a client sends and a stale browser tab cannot clobber them: `packages`,
`datasets`, and the agent sections. Two are additionally **stripped on share**: `agents` and
`agentAttachments` are removed from the copy served behind a share link, so a
shared dataflow never carries them and they can never be required.

## What lives in the manifest, not here

**Nodes are defined by package manifests.** A node's `type` is a coordinate
(`<packageId>/<templateId>` or `…@<major>`) into a manifest's `templates[].id`,
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
correspond to a template under `packages/`. Every check also refuses a node in
two scenarios and a scenario member that is not a node.

Snapshots inside `dataflowProvenance.versions` are held to a **relaxed** version
of the same shape, requiring only `nodes` and `edges`.

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
curated gallery examples only: `docs/examples/dataflows/` is hand-tuned fixture
material, and `.curio/` is your own work.

CI validates the committed examples on every push. It cannot see your own
projects, since `.curio/` is gitignored, which is what the CLI is for.
