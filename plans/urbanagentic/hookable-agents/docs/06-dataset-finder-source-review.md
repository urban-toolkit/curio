# Dataset Finder Source Review

## Purpose And Ownership

Dataset Finder is a discovery-and-selection agent for configuring a data-loading step. It reads
the authorized mission, node context, catalog metadata, geography, and lineage, then proposes
ranked candidates in the unified attached-agent chat. It does not author fetch code, mutate the
flow/Trill silently, or install an agent automatically.

The lifecycle is explicit:

1. The user chooses `Install in project` for Dataset Finder from **Global Catalog** or **My
   Imports** when the active project does not already have a template. Importing a manifest package
   only creates a private account definition; it never installs or publishes it.
2. The user drags Dataset Finder from the active project's action-free AGENTS palette to a
   compatible Data Load node.
3. Curio creates a private, unversioned attached instance identified by `attachmentId`; opening its
   dock tile resumes unified chat. `Attachment settings` may tighten Cost, Quotas, and Resource
   policies but cannot edit prompts, publish, release, version, or share the instance.
4. Switching projects replaces the palette and does not carry the attachment, chat, settings, or
   selections into the new project.

See `02-hook-model-and-flows.md`, `08-unified-agent-chat.md`, and
`11-agent-manifest-and-product-model.md` for the shared lifecycle and UI contracts.

## Two-Lane Suggestions

Dataset Finder posts one inline suggestions card with two labeled lanes:

| Lane | Candidate type | Confirmed handoff |
| --- | --- | --- |
| **External sources** | APIs, endpoints, public portals, documents, or databases not already represented by a reusable catalog dataset | A reviewed request to **Node Builder**, which owns fetch code, parameters, authorized credential-profile requirements, parsing, errors, and output format. |
| **From your Data Catalog** | Reusable datasets already visible to the user through the existing Data Catalog | The existing dataset-only install/select flow; the catalog dataset may be installed when required and authorized. This never imports or installs an agent. |

Rows are multi-selectable and informational. They do not have `Use source`, `Create node`,
`Install agent`, or other bespoke workflow buttons. The agent writes a primary suggested prompt
into the editable chat input and may offer alternative prompt chips; the user reviews, edits, and
submits a prompt to confirm the selected handoffs. Generic chat and settings controls remain
available.

There is no inline dataset-preview link in the suggestions card. Detailed catalog inspection and
preview continue through the existing Data Catalog drawer detail surface. External candidates show
enough safe metadata to support selection without claiming that an executable connector already
exists.

## Candidate Row Contract

Each row may show:

- source or dataset name;
- lane and source type (`API`, `endpoint`, `portal`, `catalog`, `document`, or `database`);
- provider or publisher;
- safe public URL/endpoint where applicable;
- expected format and geographic/temporal coverage;
- catalog installation state where applicable;
- confidence/fit score with a plain-language rationale;
- permission, provider-profile, or credential-profile requirement without exposing a secret; and
- selection state communicated by label/control state, not colour alone.

Agent/tool content is untrusted. Text, links, and metadata use the centralized allowlist renderer;
unsafe schemes, active HTML, scripts, event handlers, and unapproved embeds are rejected.

## Review And Apply Flow

1. Dataset Finder posts ranked candidates in both lanes.
2. The user selects one or more rows and submits the generated or edited confirmation prompt.
3. External picks create explicit Node Builder handoff proposals. Node Builder returns a reviewable
   fetch-node preview before any graph mutation.
4. Catalog picks enter the existing dataset-only install/select flow and preserve its authorization,
   duplicate, loading, error, and review behavior.
5. After approval, the resulting node or selected catalog dataset is represented visibly in the
   private flow/Trill and carries source/provenance metadata.
6. The Dataset Finder transcript records suggestions, selections, handoffs, failures, retries, and
   committed results; it is the private execution history, not Prompt Audit governance history.

Examples such as `NOAA Climate Data API`, `Census ACS 5-year API`, and `City Open Data Portal` are
illustrative candidates for a heat-vulnerability flow. They do not imply bundled connectors,
credentials, availability, or automatic installation.

## Interaction And Privacy Rules

- Review before apply is mandatory; a suggestion or selection alone never changes the flow.
- Slow searches preserve prior committed results and expose cancellable/retryable progress without
  replaying provider or tool side effects automatically.
- Duplicate catalog selections collapse into the existing installed/selected state; repeated
  confirmation is idempotent.
- Missing, malformed, unavailable, unauthorized, or credential-gated sources remain explainable
  failures and never trigger a silent Local-to-Remote/provider fallback.
- The private attached-agent dock, chat, selections, source URLs not present in visible output,
  catalog records, generated code, credentials, tools, providers, settings, and history are not
  exposed in the shared result.

## Visual Direction

- Use the shared attached-agent dock and unified chat visual system; do not recreate a Dataset
  Finder-specific review panel or modal.
- Use a small green identity accent for the data-oriented agent while keeping labels as the source
  of meaning.
- Present the two lanes in one grouped suggestions surface with keyboard-operable multi-select
  rows, clear focus, selected, loading, empty, error, and disabled states.
- Keep resulting source/provenance visible on the created node or catalog selection so the effect
  of the confirmed action is not hidden.
