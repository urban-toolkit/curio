# PNG Concepts

## Purpose

The PNG concept set replaces the earlier SVG-first delivery requirement for this pass. The goal is to provide presentation-ready visual explorations that stay close to the current Curio UI.

The PNGs should be read as design ideas, not production-ready implementation screens.

> Lifecycle update status: the PNG/SVG/workbook artifacts have been **regenerated** to the
> finalized model. They now show `Global Catalog` / `My Imports` / `Installed in this project`
> (imported-only Publish, project-only palettes/defaults), the six dedicated settings screens
> (Cost, Quotas, Resource policies, Prompt quality, Prompt editor, Prompt audit), the settings
> scope-applicability matrix (Account policy / Imported definition / Project agent default /
> Attached instance — each project install materializes its own defaults; attachments only
> tighten them), and reviewed `Install in project` orchestration (no auto-install). The built-in
> node Explanation tab is **retained** (`DEC-041`, `dev/18`) — concepts depicting its removal are
> stale on that point. Agents rely on the system's **existing** sharing behavior;
> there is no dedicated agent-sharing screen. Where a text specification and an image differ, the
> specification is authoritative.

## Visual Baseline

The concepts follow the references in `png-ideas`:

- black Curio top navigation
- live Curio logo asset and 65px app-menu height
- repo-backed Font Awesome icons for the built-in node palette and common Curio controls
- light dotted canvas
- compact left built-in tool palette
- right sidebar drawer
- card-based catalog list
- orange selected/action accent
- thin borders, subtle shadows, dense operational UI
- supersampled PNG rendering for smoother line art and text

## Concept Coverage

| PNG | Purpose |
| --- | --- |
| `01-agents-catalog-drawer.png` | The three-scope lifecycle drawer (scope tabs **Global Catalog** / **My Imports** / **Installed in this project**) using the **exact Data / Node Catalog card controls**: a dark `Install` primary, a neutral `Uninstall` secondary, the shared `Publish` → `Published` pill (My Imports), `Delete`, and an `Import package` footer. Global active. |
| `02-main-dataflow-attached-agents.png` | Show multiple attached agents in a single dataflow. |
| `03-attachment-dataset-finder-to-data-load.png` | Attaching Dataset Finder opens its chat; suggestions arrive in **two lanes** — **External sources** (Node Builder) and **From your Data Catalog** (install), each with per-row badges and install-state chips. |
| `04-attachment-node-explainer-to-node.png` | Attach by dragging Node Explainer from the active project's AGENTS palette onto a compute node. *(Stale detail, `DEC-041`: the image omits the built-in Explanation tab, which is retained; chat is a coexisting, not sole, explanation workflow.)* |
| `05-attachment-dataflow-builder-to-canvas.png` | Attach by **dragging Dataflow Builder from the AGENTS palette** onto the canvas. |
| `06-agent-refinement-sidebar-open.png` | The unified agent chat drawer for Node Explainer — conversational refinement and lightweight behaviour choices stay in chat; durable policy/prompt governance opens from the header cog. |
| `07-dataset-finder-overview.png` | The session history showing **both paths**: an external pick hands off to Node Builder (hand-off card), and a catalog pick is installed via the existing install flow (install card). |
| `08-dataset-review-modal.png` | The **Node Builder-generated** dataset node (spawned by Dataset Finder): fetch code, provider/credential-profile requirement, request params, a parsing / error-handling / output-format checklist, and a data sample — added by sending a **suggested prompt** from the input (no card button). Secret values are never shown. |
| `09-datasets-created-in-palette.png` | The real DATA palette distinguishing the **Node Builder-authored external node** (`EXTERNAL` · Node Builder) from the **auto-installed catalog dataset** (`IMPORTED` · Data Catalog). |
| `10-dataflow-builder-orchestration.png` | Dataflow Builder orchestration; a missing specialist is added via a **reviewed `Install in project`** proposal, never auto-installed. |
| `11-agents-palette.png` | The active project's installed-template palette. Rows are fully draggable and action-free; switching projects replaces the list. |
| `12-agent-settings-cost.png` | Project agent settings (shared six-screen modal) — Cost: per-run/rolling budgets, usage meter, alert thresholds, pricing effective date, and Estimated vs Actual labels. |
| `13-agent-settings-quotas.png` | Quota screen with execution/token/tool/concurrency limits, reservations, reset window, and locked inherited values. |
| `14-agent-settings-resource-policies.png` | Resource-policy screen with provider profile/model/locality (Local vs Remote), egress, context/output, timeout, tool/network; secrets never shown. |
| `15-agent-settings-prompt-quality.png` | Prompt-quality screen with pinned suite/rubric/threshold, evaluation status, findings, and cost/usage. |
| `16-agent-settings-prompt-editor.png` | Owned My Imports prompt draft editor with variables/schema validation, diff, and `Save draft`; immutable definition bytes remain unchanged. |
| `17-agent-settings-prompt-audit.png` | Versioned privacy/security/compliance audit rules, findings, and authorized append-only prompt-governance history distinct from the execution transcript. |
| `18-agents-drawer-lifecycle.png` | The lifecycle as a vertical flow across Global Catalog / My Imports / Installed in this project: Import-only-to-private, imported-only Publish, separate Install in project, and Attach. |
| `19-settings-scope-applicability.png` | A matrix showing how each settings screen applies across Account policy, owned Imported definition, Project agent default, and Attached instance (own / inherit / read-only). |
| `20-node-explainer-only-workflow.png` | **Obsolete concept (`DEC-041`)** — it depicted a node without an Explanation tab, which contradicts the retained tab; do not use as implementation reference. Any regeneration must show the tab present with `Explain with Node Explainer` as an additional entry into project install/attach/chat. |
| `21-agents-catalog-my-imports-publish.png` | The **My Imports** scope of the drawer: owned imported definitions with the **exact catalog publishing controls** datasets/node packs use — dark `Install`, the shared `Publish` → `Published` pill that lists the definition in the global **Catalog Hub**, and `Delete`. Publishing is imported-only. |

Conversational refinement and execution use one unified chat drawer; reusable policy and prompt
governance use one shared six-screen settings modal — see `08-unified-agent-chat.md`.
The Dataflow Builder is the master orchestration agent — see `09-agent-architecture.md`
(LangChain definition vs UI assignment) and `10-prompt-architecture.md`.

## UI Decisions Represented

- The Agents drawer lives on the right and separates Global Catalog, My Imports, and Installed in
  this project.
- Agents are reusable building blocks, not only problem-specific workflow templates.
- Agent Catalog entries use bot-head icons consistently.
- The Curio node palette uses repo-backed built-in node icons from the Curio package manifest.
- Attached node-level agents appear as dock tiles beneath their target node.
- Canvas-level agents appear as a dock or status strip attached to the canvas.
- Attachment previews begin from an active-project AGENTS palette row and use a colored path to a
  compatible target. The attachment has no SemVer/Publish/Share UI.
- The Dataset Finder does discovery + selection across two lanes (external + Data Catalog); it
  never authors fetch code. External picks hand off to Node Builder (which generates the
  reviewable fetch node); catalog picks reuse the existing install flow (auto-install if
  needed). See `06-dataset-finder-source-review.md` for the canonical two-lane contract.
- Clicking an attached-agent dock tile opens conversational refinement in the right sidebar. A
  labeled chat-header cog opens downward-only instance settings; owned imported-definition details
  own prompt governance/Publish; project-installed details own Project agent settings and
  Uninstall from project. Palette rows remain action-free.
- Agent-private data is not exposed in the shared result; the public result view never surfaces
  live project resources.
- Nodes keep their built-in Explanation tab (`DEC-041`). Node Explainer attached-agent chat is a
  coexisting node-level explanation workflow; `agent.dataflow-explainer` remains a distinct
  canvas/full-flow behavior.

## Source

The PNG concepts are generated from:

```text
sources/render_hookable_agents_png_concepts.py
```

The renderer draws at a higher internal scale and downsamples with high-quality filtering. This is the canonical source for the polished PNG pass.

The renderer has not yet been updated for planned screens `12` through `22`, the lifecycle/share
changes, or the cog entry points. (The former Explanation-tab-removal item is cancelled —
`DEC-041`; renders must show the tab present.) Those rows specify required future artifacts, not
files currently present in the concept directory.

**Header split (`DEC-042`, `dev/21`) — regenerated 2026-07-21.** All PNG/SVG concepts and the
workbook were re-rendered with the split: opened-agent-view screens (`03`, `06`, `07`, `08`,
`10`) show the agent identity/cycling/session details and Close in the single dark top header
(no Pin, no static `Agents Catalog` bar), and Agents Roster drawer screens (`01`, `02`, `18`,
`21`) show the static header with the Pin only (no `✕`). Both drawers render as **flush
full-height overlays** — viewport-top to bottom with a soft left edge shadow over the canvas —
matching the implementation's fixed `<body>`-portal drawers. The early hand sketches under
`../vectors/` predate the renderer and remain non-canonical for chrome details.

See `07-icon-source-map.md` for the icon mapping used by the renderer.

The earlier HTML/CSS source remains in:

```text
sources/hookable-agents-png-concepts.html
```

That HTML source is useful as a layout reference, but the canonical PNG renderer for this pass is the Python source.
