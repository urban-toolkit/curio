# Messages

What the runtime tells a model about what the model wrote: a tool call it does
not run, a proposal it does not make or makes for the user's review, a plan, a
request, code or a document it sends back for another attempt, and the notes a
next attempt is given. One section per message, by the id the check reads it
by. A `{name}` is a value the check fills when it says the message, such as a
node's id or the problems it found; a section names each value its check
gives, and only those.

A feature's own words are not here, even when a run reads them later: a
node's error on Play, the run journal's reason, a probe's verdict, a card or a
chat record stays with its feature.

## tool-round.plan-fence

put the plan in a ```curio.v1 fenced block as the VERY LAST thing in your reply (not ```json)

## tool-round.plan-invalid-native

[plan validation] Your dataflowPlan was invalid and was NOT shown to the user. Fix exactly these problems and call {plan_tool} with the COMPLETE corrected plan (all nodes and edges):
{listed}

## tool-round.plan-invalid

[plan validation] Your dataflowPlan block was invalid and was NOT shown to the user. Fix exactly these problems and resend the COMPLETE corrected block (all nodes and edges, same fence syntax):
{listed}

## tool-round.tool-fence

put the tool request in a ```curio.v1 fenced block as the VERY LAST thing in your reply (not ```json, and with no text after it)

## tool-round.tool-invalid-native

[tool validation] Your tool request was invalid and was NOT shown to the user. Fix exactly these problems and call the tool with the COMPLETE corrected arguments:
{listed}

## tool-round.tool-invalid

[tool validation] Your tool request block was invalid and was NOT shown to the user. Fix exactly these problems and resend the COMPLETE corrected block (same fence syntax):
{listed}

## tool-round.not-granted

tool {tool} is not granted for this run

## tool-round.egress-spent

the egress budget is exhausted ({calls} web calls per run): report what you verified so far

## tool-round.not-available

tool {tool} is not available

## tool-round.final-round

No further tool calls are available this turn: answer with what you have.

## tool-round.not-run

not run: one tool call per reply, and this reply's first call was the one run. Call this one again on its own if you still need it.

## tool-round.no-such-tool

there is no tool named {name}

## tool-round.invalid-call

invalid call, not run. Fix exactly these problems and call it again:
{listed}{final_note}

## tools.result-truncated

…[truncated: result exceeded the tool output bound]

## tools.example-key-invalid

params.key must be an example's key; call examples.read with no key to list the keys

## tools.dir-names-invalid

params.dirNames must be a non-empty list of package dirName strings

## tools.goals-shortened

node goals shortened to fit the tool output bound

## mint.no-saved-spec

no saved project spec is available

## tools.unknown-read-tool

unknown read tool {tool_id}

## tools.tool-failed

tool failed: {exc}

## tools.egress-refused

refused by the egress policy

## tools.url-required

params.url must be a non-empty URL string

## tools.endpoint-unreachable

the endpoint is unreachable: {exc}

## tools.query-required

params.q must be a non-empty query string

## tools.search-not-configured

web search is not configured for this deployment: CURIO_SEARCH_URL (--agent-search-url) has no {q} where the query goes - verify direct URLs with web.fetch instead

## tools.search-provider-failed

the search provider failed: {exc}

## tools.no-node-id

no nodeId given and this agent is not attached to a node

## tools.node-not-in-spec

node {node_id} not found in the saved spec

## mint.dataset-id-required

params.datasetId must be a non-empty dataset id string

## mint.dataset-not-in-catalog

dataset {dataset_id} is not in this project's Data Catalog: propose only ids from catalog.search results

## mint.data-catalog-unavailable

the Data Catalog is unavailable: {exc}

## mint.dataset-already-installed

dataset {title} is already installed in this project: tell the user instead of proposing

## mint.dataset-install-proposed

proposal {proposal_id} created to install dataset {name}; it awaits the user's explicit review: do NOT assume it was installed

## mint.package-miss-hint

use the dirName shown in parentheses after '(package …)' in the 'Installed but NOT enlisted in this project' list

## mint.package-miss-hint-catalog

or a dirName from packages.catalog results

## mint.dir-name-required

params.dirName must be a non-empty package dirName string

## mint.nodes-catalog-unavailable

the Nodes Catalog is unavailable: {exc}

## mint.package-ambiguous-major

package {dir_name} names more than one major in the Nodes Catalog; propose exactly one of: {candidates}

## mint.package-not-in-catalog

package {dir_name} is not in the Nodes Catalog: {hint}

## mint.package-built-in

package {name} is built-in: always present, never proposed; tell the user it is already available

## mint.package-already-installed

package {name} is already installed in this project: tell the user instead of proposing

## mint.package-install-proposed

proposal {proposal_id} created to install package {name}; it awaits the user's explicit review through the package install dialog: do NOT assume it was installed

## mint.new-template-where-source

its source file {source}

## mint.draft-justification-required

the review needs your reasoning: this draft adds the new node type{s} {names}, so the build request needs a "justification" beside "mode" that names the closest existing templates you considered and why each is inadequate

## mint.draft-justification-too-long

the justification is {length} characters and the review card shows at most {max_chars}: name the closest existing templates and why each is inadequate, briefly

## mint.template-registry-unavailable

the node template registry is unavailable: {exc}

## mint.draft-template-duplicates

the new template {template_id} matches the existing template {twin_id} ({twin_label}): that is reuse territory. Use {twin_id} instead of a new node type; when it cannot do the job, give the new template a label no existing template has, and say in the justification why {twin_id} is inadequate

## mint.new-template-ungrounded

the new template {template_id}, {where}: {refusal}

## mint.draft-request-invalid

invalid build request: {exc}

## mint.draft-build-unavailable

the package build service failed to start: {exc}

## mint.draft-build-incomplete

the package build did not complete (phase {phase}): {details}. Revise the draft and request package.draft.apply again

## mint.draft-proposed

proposal {proposal_id} created: {summary} (artifact {digest}…). It awaits the user's explicit review of the diff, dependencies, and preview: do NOT claim the package or its nodes exist until the user applies it

## mint.no-conversation

proposals need a persistent conversation; this attachment has none

## mint.no-proposal-flow

no proposal flow exists for tool {tool}

## mint.plan-params-invalid

your dataflowPlan was invalid: fix exactly these problems and resend the complete corrected request:
{listed}

## mint.content-required

params.content must be a non-empty string

## mint.content-too-large

params.content exceeds the proposal size bound

## mint.content-write-proposed

proposal {proposal_id} created for node {node_id}; it awaits the user's explicit review: do NOT assume it was applied

## mint.widgets-not-placeable

params.widgets: a {label} node cannot hold widgets; a widget is placed in a node's code or spec

## mint.appearance-invalid

params.appearance: {exc}

## mint.node-create-proposed

proposal {proposal_id} created for a new {label} node; it awaits the user's explicit review: do NOT assume it was applied

## mint.specialist-no-conversation

specialist {coord} is not installed and this attachment has no conversation to carry an install proposal: ask the user to install it

## mint.specialist-install-proposed

specialist {coord} is not installed in this project; an Install proposal ({proposal_id}) awaits the user's explicit review: do NOT assume it was installed or that the delegate ran

## plan.fanin-existing-note

(plus {existing_count} existing connection{s})

## plan.fanin-no-inputs

target {label} ({node_type}) accepts no inputs: remove the edge(s) from {src_list}

## plan.fanin-single-input

target {label} ({node_type}) accepts 1 input but the plan wires {total}{existing_note}: wire {src_list} into one node that takes several inputs (a code step that combines them), and connect that node to the target

## plan.fanin-too-many-inputs

target {label} ({node_type}) accepts at most {max_inputs} inputs but the plan wires {total}{existing_note}: reduce the fan-in

## plan.handle-invalid

edges[{i}].toHandle {handle}: this node's inputs are {circles}

## plan.no-conversation

proposals need a persistent conversation

## plan.nodes-carry-content

plan nodes must not carry content: plans describe intent; node content is generated and validated per node after creation. Remove the content from: {content_refs}

## plan.node-problem

plan node {ref}: {problem}

## plan.revision-targets-invalid

the plan's revision targets are invalid:

## plan.widgets-scenarios-invalid

the plan's widgets or scenarios are invalid:

## plan.fanin-invalid

the plan wires invalid fan-in:

## plan.spatial-join-invalid

the plan's Spatial Join settings are invalid:

## plan.remove-node-unknown

removeNodes: {node_id} is not a node in the saved dataflow; use real node ids (dataflow.read shows them)

## plan.remove-edge-unknown

removeEdges: {edge_id} is not an edge in the saved dataflow

## plan.edge-endpoint-unknown

edges[{i}].{label} {endpoint} is neither a plan ref nor an existing node id

## plan.interaction-edges-invalid

the plan wires invalid interaction edges:

## plan.edge-closes-cycle

edge {source} → {target} closes a cycle: {cycle}

## plan.creates-cycle

the plan creates a cycle in the dataflow (data edges must form a DAG):

## plan.cycle-remedy

remove one data edge of the loop, or, where it should carry selections between two views, make that edge "kind": "interaction"

## spatial-join.not-object

{where} must be an object, such as {"predicate": "within", "output": "counts"}

## spatial-join.unknown-keys

{where} has keys a Spatial Join does not: {unknown} (it has {setting_keys})

## spatial-join.not-a-join

{where}: a {label} node has no operation or output; only a Spatial Join node takes {key}

## plan.widgets-not-placeable

plan node {ref} ({label}) cannot hold widgets: a widget is placed in a node's code or spec, or held by a Parameter node

## plan.scenario-name-taken

scenarios[{index}] {name}: the dataflow already has a scenario named {name}: each scenario needs its own name

## plan.scenario-member-unknown

scenarios[{index}] {name}: {member} is neither a ref of this plan nor an existing node id (dataflow.read shows them)

## plan.scenario-member-taken

scenarios[{index}] {name}: {member} is already in the scenario {owner}: a node belongs to one scenario

## acquire.source-and-resource-required

a download needs both a sourceId and a resourceId

## acquire.unknown-source

there is no Discovery Catalog source {source_id} here; this deployment connects to {known}

## acquire.source-offers-no-downloads

{name} does not offer downloads

## acquire.storage-source-not-offered

{name} is a storage source; add its resources from its page in the Discovery Catalog

## acquire.service-source-not-offered

{name} downloads for an area set on its page in the Discovery Catalog

## acquire.model-source-not-datasets

{name} adds models to the Model Catalog, not datasets

## acquire.already-held

{title} is already in the user's Data Catalog from this resource - tell them instead of proposing a second copy

## acquire.credential-required

{exc} - ask the user to add the {secret_id} token in API Settings{help}. Never ask them to paste it to you.

## acquire.describe-failed

{name} could not describe {resource_id}: {exc}

## acquire.format-not-offered

that resource is not offered as {fmt}; it offers {offered}

## acquire.format-not-offered-none

nothing this catalog can ingest

## acquire.proposed

proposal {proposal_id} created to download {name} from {source}; it awaits the user's explicit review - do NOT assume it was downloaded

## request.not-object

toolRequest must be an object

## request.tool-not-an-id

toolRequest.tool must be a tool id like node.create

## request.params-not-object

toolRequest.params must be an object

## request.content-too-long

{where} is {count} chars (max {proposal_content_max_chars})

## request.params-rest-too-big

the params other than {where} are {rest_bytes} bytes (max {max_bytes}): put the code in {where}, not in other fields

## request.params-too-big

toolRequest.params is {params_bytes} bytes (max {budget})

## plan.field-not-string

{where} must be a string

## plan.field-empty

{where} must not be empty

## plan.field-too-long

{where} is {count} chars (max {max_chars})

## plan.removal-not-list

{key} must be a list of ids

## plan.removal-too-many

{key} has {count} entries (max {max_entries})

## plan.removal-duplicate

{key}[{i}] duplicates {entry}

## plan.not-object

dataflowPlan must be an object

## plan.changes-nothing

the plan changes nothing: add nodes, add edges (existing node ids allowed), make scenarios, or remove nodes/edges

## plan.too-many-nodes

nodes has {count} entries (max {max_nodes})

## plan.ref-reused

{where}.ref {ref} is used by an earlier node: refs must be unique

## plan.node-content-not-string

{where}.content must be a string

## plan.node-content-too-long

{where}.content is {count} chars (max {proposal_content_max_chars})

## plan.edges-not-list

edges must be a list

## plan.too-many-edges

edges has {count} entries (max {max_edges})

## plan.edge-endpoint-removed

{where}.{label} references {value}, which this plan removes

## plan.edge-kind-unknown

{where}.kind {kind_raw} is not one of {plan_edge_kinds}

## plan.interaction-edge-to-handle

{where}: an interaction edge has no input circle: drop toHandle

## plan.edge-to-itself

{where} connects {src} to itself

## plan.edge-duplicate

{where} duplicates an earlier {src}→{dst} {kind} edge{on_handle}

## plan.too-big-with-copies

with its copies the plan has {nodes} nodes and {edges} edges (max {max_nodes} and {max_edges})

## plan.parameter-one-widget

{where} is a Parameter node, which holds exactly one widget: give it in widgets

## plan.block-not-json

the block is not valid JSON: {exc}

## request.block-not-json

the block is not valid JSON: {exc}

## request.delegate-not-object

the delegate request must be an object

## request.delegate-capability-not-an-id

capability must be a capability id like node.content.generate

## request.delegate-inputs-not-object

inputs must be an object

## request.delegate-inputs-not-json

inputs is not JSON-serializable: {exc}

## request.delegate-inputs-too-big

inputs is {size} bytes (max {budget})

## request.params-not-json

toolRequest.params is not JSON-serializable: {exc}

## plan.node-not-object

{where} must be an object

## plan.edge-not-object

{where} must be an object

## scenario.nodes-missing

{where}.nodes must list the scenario's nodes: refs of this plan or existing node ids

## scenario.too-many-nodes

{where}.nodes has {count} entries (max {members_max})

## scenario.member-removed

{here} {member} is a node this plan removes

## scenario.member-taken

{here} {member} is already in the scenario {owner}: a node belongs to one scenario

## scenario.copies-missing

{where}.copies must name a ref for the copy of each node of {name}: {skeleton}

## scenario.copies-incomplete

{where}.copies names no copy for {missing}

## scenario.copies-extra

{where}.copies names {extra}, which {name} does not hold

## scenario.copy-ref-taken

{here} {ref} is already a ref of this plan: a copy needs a ref of its own

## scenario.values-not-map

{where}.values must map a copy's ref to its widget values

## scenario.values-not-a-copy

{here}: {ref} is not a copy this duplicate makes ({original_of})

## scenario.values-not-widget-map

{here} must map widget names to values

## scenario.values-unknown-widget

{here}.{name}: the node has no widget named {widget}{widgets_it_has}

## scenario.values-widgets-it-has

(it has {widgets})

## scenario.duplicate-unknown

{where}.duplicateOf {source_name} names no scenario earlier in this list

## scenario.duplicate-outside-plan

{where}: {source_name} holds {outside}, which is not a node this plan adds; a duplicate copies the nodes this plan adds

## scenario.not-list

scenarios must be a list of scenarios

## scenario.too-many

scenarios has {count} entries (max {scenarios_max})

## scenario.not-object

{where} must be an object

## scenario.unknown-keys

{where} has keys a scenario does not: {unknown} (a scenario has {scenario_keys})

## scenario.name-taken

{where}.name {name} names an earlier scenario: each scenario needs its own name

## scenario.selection-or-duplicate

{where} must give either nodes (a selection) or duplicateOf (a duplicate)

## scenario.color-format

{where}.color {color} is not a #RRGGBB color

## scenario.values-need-copies

{where}.values needs copies: the refs the copies take

## widget.value-not-json

{where} is not a JSON value

## widget.value-too-long

{where} is {count} chars as JSON (max {value_max_chars})

## widget.options-not-object

{where} must be an object

## widget.options-unknown-keys

{where} has keys a widget's options do not: {unknown} (they are {option_keys})

## widget.choices-shape

{where}.choices must be a list of up to {choices_max} texts

## widget.display-choice

{where}.display must be one of {choice_displays}

## widget.option-not-number

{where}.{key} must be a number

## widget.units-shape

{where}.units must be a text of up to {units_max_chars} chars

## widget.not-object

{where} must be an object

## widget.unknown-keys

{where} has keys a widget does not: {unknown} (a widget has {widget_keys})

## widget.label-shape

{where}.label must be a text of up to {text_max_chars} chars

## widget.not-list

{where} must be a list of widgets

## widget.too-many

{where} has {count} widgets (max {max_widgets})

## widget.field-not-text

{where}.{key} must be a text

## document.not-json

the document is not valid JSON: {exc}

## document.vega-not-object

a Vega-Lite document must be a JSON object

## document.vega-inputs-geometry

{where} reads {column}, a geometry column, but the dataset {inputs_dataset} stacks its inputs' rows without their geometry; a view that draws it reads one input's own dataset, input_0 for the first circle, input_1 for the second

## document.vega-unknown-field

{where} reads {field}, which is not a column of this node's input; available columns: {available} (plus {added}, added by Curio)

## document.vega-schema-mismatch

{error}: the document does not match the Vega-Lite schema

## document.autk-not-object

an Autark grammar document must be a JSON object

## document.autk-wrong-type

{where}: expected {types}, not {given}

## document.autk-one-of

one of {choices}

## document.root-name

the document

## document.autk-runs-nothing

the document has nothing for Autark to run; it must be {shape}

## document.autk-map-no-layers

"{where}.{layers}" is empty, and a map with no layers renders nothing

## document.autk-shape-fallback

an Autark grammar JSON document

## document.vega-shape

a Vega-Lite JSON document: {"$schema": "{schema_url}", "mark": …, "encoding": …}. Do NOT include a "data" block: Curio injects this node's input as the data at render time

## document.json-shape

a JSON document

## document.no-document

there is no document here at all{reply}; this node's content must be {shape}

## document.no-document-reply

(the reply was {reply})

## document.prose-not-document

the reply is prose, not a document ({reply}…); this node's content must be {shape}

## document.refused

document refused: this node's content is a {what} document and it does not validate: {detail}. Fix exactly that and return the whole document; nothing is written to the node until it validates.

## document.autk-shape

an Autark grammar JSON document, such as the map {"map": {"{layers}": [{example_layer}]}}, where "{first}" is this node's first input. A document names at least one of {families}; a plot needs {plot_fields}; a compute pass needs {compute_fields}, plus {compute_one_of}; a loader is {"data": [{"type": "{source_type}", ...}]}

## result-shape.consumer-no-output

the code returned no output (None), which downstream node {label} cannot accept (it declares {declared}): return the data this node produces, or, if it cannot be produced (its source cannot be read, or its inputs cannot be joined), say so in one line instead of returning code

## result-shape.consumer-type-mismatch

the output type {output_data_type} is not accepted by downstream node {label} (declares {declared})

## context.content-truncated

…[truncated: content exceeds the context bound]

## result-shape.null

the code ran and produced {count} row{s}, but every sampled value of {named} is NULL: the result has rows and no data in them

## result-shape.null-inputs

Its inputs were: {described}

## result-shape.null-advice

A join that matched nothing with how="left" (or a fill) does exactly this: compare the key columns' VALUES, not their names, and join on columns whose values are the same kind of thing. Never keep rows of nulls, fabricate values, or let a join that matched nothing stand so the dataflow can proceed. If these inputs cannot be joined, say so in one line and return no code.

## result-shape.empty

the code ran but produced an EMPTY result: 0 rows{of}

## result-shape.empty-out-of

out of a {output_data_type}

## result-shape.empty-inputs

Its inputs were NOT empty: {described}

## result-shape.empty-advice

A join, merge or filter matched nothing: compare the key columns' VALUES, not their names, since two columns can both look like an id and describe different things (a community-area number is not a census tract id). Either join on columns whose values are the same kind of thing, or, if they cannot be joined, say so in one line with no code.

## result-shape.empty-render

the document is valid and its last render drew NOTHING: {message}

## result-shape.empty-render-inputs

This node's input holds: {described}

## result-shape.empty-render-advice

Encode fields that exist and hold values, and remove any filter or scale domain that excludes every row; return the whole document.

## result-shape.absent

the code ran and returned NO output{typed}: a node must return the data it produces, and nothing downstream can read an absent output

## result-shape.absent-typed

(the sandbox typed it {output_type})

## result-shape.absent-conclusion

Your code says: {conclusion}. If that is your conclusion, return that sentence as your whole answer, with no code at all, and it is recorded as this node's honest outcome

## result-shape.absent-decline

If this node cannot produce its data (its source cannot be read, or its inputs cannot be joined), say so in one line with no code, and it is recorded as this node's honest outcome

## result-shape.absent-given

What you were given: {described}

## input-contract.refused

input contract refused: {count} inputs reach this node on one circle, so `{circle}` is a LIST of them in order: {body}. Your code used `{used}`: a list has no attribute {attribute_name}. Read the input you need by its index ({chips}, ...): `{circle}` alone is the list itself.

## topology.edit-features-other-node

edges[{i}]: an interaction edge joins the {editor_type} node to an {map_type} map it feeds, and to no other node; {other} is {other_type}: use a data edge

## topology.edit-features-not-fed

edges[{i}]: an interaction edge joins the {editor_type} node to an {map_type} map it feeds, and {editor} does not feed {other}: add a data edge from {editor} to {other}, or link {editor} to the map it feeds

## topology.interaction-edge-refused

edges[{i}]: an interaction edge links two views when one of them highlights what it receives ({highlighters}), or links a view ({views}) or a {pool_names} to a {pool_names}; {offender} is {offender_type}: use a data edge, or end the interaction edge at a view that highlights or at a {pool_names}

## grounding.unrequested-dataset

{read_at}: loads the Data Catalog dataset {dataset}, but the user asked for {asked}; load the dataset the user asked for, or ask the user before using another one

## grounding.not-in-catalog

{call}({literal}) (line {line}): not a {kind} in this project's Data Catalog: use the id of a catalog.search row

## grounding.path-from-prefix

{where}: the file name is composed at run time from a prefix; write the complete path as one literal so it can be grounded

## grounding.local-file-unseen

{where}: a local file Curio cannot see; the user gave no such path and no Data Catalog dataset resolves to it

## grounding.url-unverified-no-probe

{where}: not verified this run and no probe is available; only a URL the runtime has verified may be fetched

## grounding.url-400

answered 400, so the endpoint exists but this request shape is wrong; check the parameters

## grounding.egress-refused-detail

refused by the egress policy ({detail})

## grounding.url-unchecked

could not be checked

## grounding.url-unverified

{where}: {why}. Only a URL the runtime verified may be fetched

## grounding.list-more

and {count} more

## grounding.unknown-function

{name} (line {line}): Curio gives node code no {name}, and this code neither defines nor imports one; the functions {engine} code has: {has}

## grounding.function-not-in-engine

{name} (line {line}): {engine} code has no {name}, only {engines} code does; the functions {engine} code has: {has}

## grounding.item-computed

{call} (line {line}): write its {argument} as a string in the call, such as {call}("<{argument}>"), since Curio reads {reads} from the code before the node runs

## grounding.model-none-added

none added

## grounding.model-added

added: {names}

## grounding.secret-saved

saved: {names}

## grounding.model-unknown

{call}({item}) (line {line}): no model {item} among this account's models ({models}); load one of those, or ask the user to add it with Add in the Model Catalog

## grounding.secret-none-saved

none saved

## grounding.secret-unknown

{call}({item}) (line {line}): no connection key named {item} ({saved}): save one in API Settings, API keys, then keep the call as written

## grounding.import-not-reachable

import {name} (line {line}): {name} is a module of the package {package}, and only these nodes import it: {nodes}

## grounding.import-package-not-added

import {name} (line {line}): {name} is a module of the package {package}, which this account has not added; once the user adds it, these nodes import it: {nodes}

## grounding.code-refused

code refused, {count} problem{s} with what it calls or imports:

## grounding.code-change

Change the code as each one says; no data source is missing.

## grounding.credential-literal

{name} (line {line}): a credential literal in node code; save it as a connection key (API Settings, API keys) and write curio_secret("<name>") instead; a key value is never written into a node

## grounding.no-source

no grounded source: this data-loading node opens no file and fetches no URL, and data invented inline is fabricated evidence unless the user asked for synthetic data

## grounding.refused

source grounding refused: {count} ungrounded source{s}:

## grounding.allowed-user-path

a path the user typed in this conversation

## grounding.allowed

Allowed sources: {sources}.

## grounding.never-invent

Never invent a filename, never assume a file exists, never write a URL from memory. If no source can be grounded, ask the user for a path or URL instead of proposing.

## grounding.url-answered

answered {status}

## grounding.egress-refused

refused by the egress policy

## grounding.candidates-pending

dataset candidates are shown to the user for review: do not propose a node in this turn; end your reply by asking the user to select and confirm a source, then build from the confirmed one on the next turn

## grounding.hint-catalog-search

a `path` from a catalog.search row (granted: search first)

## grounding.hint-discover

a URL the runtime verified: delegate the dataset.discover capability to find and verify candidates first, then build from the one the user confirms

## grounding.hint-verified-url

a URL already verified in this conversation

## grounding.probe-budget-spent

the egress budget was spent before this URL, so it was not checked

## grounding.hint-synthetic

data made up in the code, ONLY when the user asked for made-up data in their own words

## grounding.hint-connection-key

a saved connection key by name: {use_lines}

## grounding.source-rule

Load catalog datasets ONLY by their id, written as a string in {dataset_calls} (a collection's in {collection_calls}), as each row's `use` line does: the sandbox resolves it. Open ONLY the local paths listed (catalogDatasets[].path or userPaths), and fetch ONLY these URLs (verifiedUrls). Never invent a filename, never assume a file exists, never write a URL from memory: the runtime refuses ungrounded content. If none of these fits the intent, return a one-line explanation of what source is missing instead of code.{keyed_host}{synthetic}

## grounding.source-rule-keyed-host

A key-gated host is reachable ONLY through a saved connection key: copy its `use` line (curio_secret("<name>"), which the sandbox resolves) and send the value the way `delivery` says (query:<param> / header:<Name> / code = as the API documents). Never write a key value into the code; if the host needs a key and availableSecrets lists none for it, return the one-line explanation naming the host.

## grounding.source-rule-no-key

A key-gated host has no saved connection key here: do not invent one; return the one-line explanation naming the host that needs a key.

## grounding.source-rule-synthetic

The user asked for synthetic data: build it inline and say so.

## dataset.candidates-finder-fallback

the agent asked for datasets

## dataset.candidates-unrecognized

{who} returned no recognizable datasetCandidates block; report that honestly, and do not invent candidates or a source

## dataset.candidates-none-usable-dropped

({dropped} catalog row(s) dropped: not in the Data Catalog)

## dataset.candidates-none-usable

{who} returned no usable candidates{note}; report that honestly, and ask the user for a path or URL instead of guessing

## dataset.candidates-shown-dropped

{dropped} catalog row(s) were dropped (not in the Data Catalog).

## dataset.candidates-shown

{total} dataset candidate(s) are shown to the user for review; external rows carry the runtime's verification verdict.{note} Do NOT propose a node in this turn: ask the user to select and confirm; you will build from the confirmed source on the next turn.

## dataset.candidates-unconfirmed

{unconfirmed} Discovery resource id(s) went unconfirmed, so their rows are not marked downloadable.

## dataset.catalog-listed

The project's Data Catalog as catalog.search returned it

## dataset.catalog-unavailable

The Data Catalog listing was empty or unavailable: the catalog lane must stay empty; say so.

## delegate.content-not-minted

the generated content could not become a reviewed proposal ({error}). Report this honestly: nothing was changed and nothing awaits review

## delegate.content-not-minted-unknown

unknown error

## delegate.content-minted-here

in this conversation

## delegate.content-minted-at-node

at the node's own {home_name} agent

## delegate.content-minted

the generated content was minted as reviewed proposal {proposal_id} for node {node_id} ({where}); it awaits the user's explicit Apply: summarize the change in one or two sentences, do NOT restate the code, and do NOT say it was applied

## delegate.reuse-existing-enlisted

It is already in this project: use it directly.

## delegate.reuse-existing-not-enlisted

It is installed but NOT in this project: propose package.install for {dir_name} first, then use its template.

## delegate.reuse-existing

the authoring delegate reports that {dir_name} already does this{reason}. Nothing was authored, which is the correct outcome.{hint} Do NOT ask for a new package that duplicates it.

## delegate.search-no-question

no 'question' input was supplied to the delegation

## delegate.search-malformed

the search provider returned malformed JSON

## delegate.notes-contract-mismatch

the delegate's reply did not match the notes reply contract (ONE JSON object with 'answer' and a 'notes' list): nothing was placed; the reply was kept as text

## delegate.notes-empty

the delegate returned no answer and no notes

## delegate.notes-not-granted

{answer}the delegate composed notes but this agent is not granted node.create: the notes were kept as text only

## delegate.notes-skipped-template-error

the chosen notes template was not available ({err})

## delegate.notes-skipped-no-template

no installed notes template was available

## delegate.notes-skipped

{answer}notes skipped: {reason}. Ask the Researcher (attached to a node or the canvas) to enlist or author a notes package; its own runs hold the reuse ladder a delegate cannot reach

## delegate.notes-none-proposed

{answer}no notes could be proposed: {last_refusal}

## delegate.notes-proposed

{answer}{count} reviewed note proposal(s) created{refusal}: they await the user's explicit Apply; do NOT claim the notes exist

## delegate.draft-empty

the delegate replied with no text at all

## delegate.draft-no-json

no JSON build request found in the reply: it must be ONE JSON object, either the whole reply or a single ```json fenced block. Prose describing the package is not a build request

## delegate.draft-not-object

the JSON is a {name}, not an object

## delegate.draft-not-build-request

the JSON parsed but is not a build request: it must carry "mode" ('create' or 'extend') and a "manifest" object (top-level keys were: {keys})

## delegate.draft-json-invalid

the JSON did not parse ({decode_errors}). If the reply was cut off mid-object, re-emit the COMPLETE build request and keep the file bodies short enough to finish

## delegate.draft-not-granted

the delegate produced a package draft but this agent is not granted package.draft.apply: the draft was kept as text only

## delegate.draft-renamed

this correction changed the package id from {pinned_package_id} to {draft_id}. Fix the SAME package: a rename does not resolve the error, it just creates a duplicate package

## delegate.draft-notes-reconciled

(the draft's {count} note(s) carry the caller's findings verbatim: runtime-reconciled from the delegation inputs)

## delegate.draft-corrected

(after {round_index} correction round(s))

## delegate.draft-rerun-failed

the authoring delegate could not be re-run to correct its draft ({attempt_text}); the last error was: {last_error}

## delegate.draft-rerun-failed-no-reply

no reply

## delegate.draft-unusable-attempts

after {rounds} attempt(s)

## delegate.draft-unusable

the authoring delegate produced no usable package draft{spent}. The last error was: {last_error}. Fix THAT and keep the same package id, or tell the user plainly that authoring failed. Do NOT re-delegate under a different package name, and if a package that already does this job is listed as installed, use it instead of authoring one

## delegate.recommend-evidence

Packages that exist for this user: the only packages you may recommend. installedInProject false means the caller must enlist the package before its templates can be used; a need none of these rows meets is a finding, not a recommendation.

## delegate.reuse-evidence

Packages that already exist for this user. If one of these already satisfies the requested need, say so and author nothing: name its dirName so the caller can use it (installedInProject false means the caller must enlist it first). Extend one by name instead of creating a near-duplicate.

## delegate.no-delegates

this agent declares no delegates

## delegate.capability-undeclared

no delegate of this agent declares capability {capability}

## dataset.confirmed-source

The user confirmed these sources for this node. Load ONLY these: a catalog row through curio_data_path("<datasetId>"), an external row from its exact url.

## delegate.result-truncated

…[truncated: delegate result exceeded the output bound]

## delegate.no-instruction

delegate {coord} has no instruction prompt available

## delegate.failed

delegate {coord} failed: {error}

## delegate.could-not-start

delegate {coord} could not start: {exc}

## turn.example-unknown-key

no worked example has the key {key}; call examples.read with no key to list the keys

## turn.example-excluded

the worked example {key} is not available in this project; call examples.read with no key to list the ones that are

## turn.context-truncated

…[truncated: context exceeded the run-context bound]

## request.call-arguments-not-json

the arguments are not valid JSON: {exc}

## request.call-arguments-not-json-object

the arguments must be a JSON object

## request.call-arguments-not-object

the arguments must be an object

## egress.body-truncated

…[truncated: response exceeded the egress body bound]

## map-edits.call-truncated

…[truncated: the call exceeds the context bound]

## map-edits.unreadable

Map Edits cannot read this code: {problem}

## map-edits.made-up-ids

Map Edits: the run says these edits name ids no feature has, so they change nothing:
{lines}{more}
Name features the input holds, by their ids or by a where condition.

## map-edits.and-more

…and {more} more

## dashboards.tile-loads-own-data

This node is pinned to the dashboard, which carries only saved outputs, so its spec cannot load its own data. Move the "data" section into a node of its own upstream, and draw that node's output here.

## solve.attempt-code-truncated

… [truncated: the attempt's code exceeded the trail's bound]

## solve.url-evidence-composed

the URL composed from the code's url + params

## solve.url-evidence-placeholder

the URL composed from the code's url + params; the saved key was sent in place of curio_secret(...)

## solve.key-not-saved

no connection key named {names} is saved; not probed

## solve.keyed-note-code-delivery

a connection key {name} is saved for this host{not_used}; the code decides how the API receives it

## solve.keyed-note-not-used

(the code does not use it yet: {use_line})

## solve.keyed-note-not-data

even with the saved key {name} sent {sent}, the request answered {content_type}{title}: the key or the way it is sent is wrong; say so instead of guessing parameters

## solve.keyed-note-answers-data

with the saved key {name} sent {sent} the request answers data, so the code must send it the same way: {use_line}{not_used}

## solve.keyed-note-not-used-yet

(the code does not use it yet)

## solve.keyed-note-outcome

with the saved key {name} sent {sent}: {status}{http_status}

## solve.after-redirect

after redirecting to {final_url}

## solve.html-page-titled

an HTML page titled "{title}"

## solve.endpoint-not-data

answered {what}{where}: not data. Read the page title: a key or sign-in requirement cannot be fixed by changing parameters; say what is missing.

## solve.endpoint-status

the request itself answered {http_status}{where}{said}

## solve.builder-declined

the content builder declined: {decline}

## solve.builder-answered

the content builder answered: {answer}

## solve.repeated-attempt

the correction repeated the previous attempt (only comments or spacing changed), not run again; change the request that failed: {previous_error}

## solve.repeated-attempt-escalated

you have now returned the same code {repeats} times. Stop repeating it: change the APPROACH (a different library call, a different key or column, a different shape of the result), or say plainly what you cannot do. {detail}

## solve.document-references-unresolved

the document's references cannot be resolved: {exc}
