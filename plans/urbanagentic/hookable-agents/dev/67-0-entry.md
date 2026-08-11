> **Status: COMPLETE — implemented 2026-08-05.** Every problem and objective in
> this entry shipped through the dev/67 memo program (`67-1-index.md` is the map):
>
> - **Invalid multiple-input topology** → `67-3` (DEC-051): fan-in is unmintable at
>   plan mint, refused at `onConnect`, and resolved by name toward the existing
>   Merge node; explicit edge handles end-to-end.
> - **Dataset Finder hallucination** → `67-4` (DEC-053): policy-gated egress, the
>   provider-agnostic verification gate (the Socrata fix covers ANY dataset API —
>   Socrata is a registry refinement), per-row verified/unverified verdicts, and
>   the Node Researcher (`research.verify`, chainable from the builder agents).
> - **Simulation Mode as the default** → `67-5`/`67-6`/`67-7`/`67-8` assembled by
>   `67-9` (DEC-054): per-node plan rows with editable goals and per-node Apply,
>   propose-mode content reviews, execute-through-node validation with bounded
>   self-correction, the named connection review stage, and the step/auto driver
>   ("Build & validate plan") with pause-on-failure and resume — bulk apply
>   demoted to the explicit "Apply all without validation".
> - **Full dataflow awareness + runtime messages** → `67-2` (DEC-052): grounded
>   context producers for the composites, the structure-first `dataflow.read`
>   (edges never truncate), and the per-node runtime journal with
>   `node.runtime.read`.
> - **LangChain** → evaluated and declined (deterministic validation stays direct
>   code); "unbounded research chains" joins DEC-021 as a monitored re-open
>   condition (recorded in `67-1` and `67-4`).
>
> Ledger: DEC-051/052/053/054 (dev/03 + 2.1 traceability); build log
> BL-P5-20260805-07..14. Verification at completion: backend 1147 passed,
> frontend 733 passed.

## Dataflow Builder — Granular Simulation, Per-Node Validation, and Orchestration Hardening

Following the Solve progress work and destruction-plan reconciliation, perform a deep but concise investigation of the remaining Dataflow Builder orchestration issues and update the implementation plan accordingly.

### Problems to address

#### 1. Invalid multiple-input topology

A node must never receive multiple independent incoming edges unless its node type explicitly supports that structure.

If two or more upstream outputs need to feed a single downstream operation, the Dataflow Builder and Curio loop harness must detect the topology requirement and introduce an appropriate existing Merge node instead of connecting multiple edges directly to an incompatible node.

The orchestration layer must:
- Inspect the target node’s supported input structure before creating edges.
- Detect when multiple inputs require a Merge node or another existing aggregation primitive.
- Search for and reuse an appropriate existing built-in or scoped custom node before considering creation of anything new.
- Never generate an invalid graph structure and defer discovery of the problem until execution.

### 2. Dataset Finder hallucination during dataflow construction

The Dataset Finder has produced invalid or hallucinated external dataset/API information during Dataflow Builder sessions, including invalid Socrata dataset codes observed in fix-loop session `89ae8123-98fc-4c5f-bd8f-9a7728d3da8d`.

External dataset discovery must therefore be treated as a verifiable research operation rather than an unvalidated LLM suggestion.

The Dataset Finder must:
- Verify external datasets and API identifiers before they are accepted into the dataflow.
- Use the Node Researcher as an actual research/web-search agent for factual validation whenever appropriate.
- Validate API endpoints, dataset identifiers, schemas, required columns, authentication requirements, and response shape.
- Never treat model-generated dataset identifiers or URLs as valid without verification.
- Be chainable from the Dataflow Builder, Node Builder, Node Content Builder, Dataset Finder, and other agents whenever external factual validation is required.

Use LangChain where it appropriately improves agent orchestration, research-tool invocation, delegation, validation chains, or multi-agent coordination. Do not replace deterministic application logic with LangChain when direct programmatic validation is more reliable.

---

## Default build model: first-class Simulation Mode

Make granular **Simulation Mode** the default Dataflow Builder workflow.

The primary objective is to make every generation step individually inspectable, executable, correctable, and explicitly approved so that the final dataflow is valid by construction rather than repaired after bulk generation.

The default workflow should no longer be:

`Plan → Create entire graph → Solve entire graph`

Instead, it should progressively construct and validate the dataflow:

`Plan → Review node → Create node → Solve node → Execute through node → Validate → Approve → Next node → Connections`

Each node should therefore be created and solved independently.

---

## Plan card behavior

The Dataflow Builder plan should describe the intended graph without embedding generated code.

Each planned node should contain:
- Node type or proposed existing-node match.
- Editable node goal/prompt.
- Relevant intent and expected input/output information.
- Per-node **Apply** action.

The node goal should be rendered as an editable input so the user can refine the intended behavior before approving node creation.

There is no concept of "trivial code" that bypasses Solve. Every generated node-content result must go through the same validation process.

---

## Per-node creation

Nodes should be created one at a time.

Clicking **Apply** on a planned node should:

1. Resolve the best existing built-in or scoped custom node type.
2. Create only that node.
3. Attach the Node Builder to the newly created node.
4. Allow the Node Builder to create or modify the node as needed.
5. Proceed to node-content generation and validation before considering that node complete.

Do not create placeholder nodes whose required content is knowingly unresolved.

Authorization to create code does not justify bulk creation of unsolved nodes.

---

## Node Builder and Node Content Builder

The Node Builder should support both:
- Creating a node.
- Modifying an existing node.

It may therefore operate as the orchestration layer around Node Content Builder behavior when a node already exists.

For generated content, preserve a dedicated Node Content Builder interaction.

The Node Content Builder should:
- Receive the full dataflow context.
- Receive the current node goal and configuration.
- Receive relevant upstream and downstream node information.
- Generate or modify the node content.
- Present the proposed content for review.
- Provide an **Apply** action that writes the generated content into the node.

The Apply interaction should behave conceptually like the legacy **Get Code** flow associated with the goal/subtask input, while using the current agent architecture.

---

## Every Solve must be validated

Every node-content generation during Solve must be validated.

There should be no shortcut for code considered "trivial."

Validation should primarily consist of executing the dataflow from its valid starting point through the node currently being solved.

For each node:

1. Generate the node content.
2. Sanitize and apply the candidate content in an isolated/reviewable state.
3. Execute the required upstream portion of the dataflow through that node.
4. Inspect runtime output, schema, logs, warnings, and errors.
5. Compare the result against the node goal and downstream requirements.
6. Allow the responsible agent to self-correct when validation fails.
7. Present the validated result to the user for approval.
8. Only then consider the node solved.

Use the existing programmatic execution infrastructure and the same meaningful execution mechanisms already exercised by the Playwright-based dataflow tests where appropriate.

---

## Full dataflow awareness

All agents participating in dataflow construction must have access to the complete relevant dataflow context.

An agent should never respond with statements such as:

> "I don't have the full dataflow edges in the current context."

The orchestration layer must provide or make retrievable:
- Nodes.
- Node types.
- Node goals.
- Current node contents.
- Edges.
- Upstream and downstream relationships.
- Dataset references.
- Known schemas.
- Execution state.
- Relevant runtime outputs.
- Logs, warnings, and errors.

Agents should be able to resolve relationships programmatically instead of asking the user to provide IDs or manually paste the dataflow specification when that information already exists in Curio.

---

## Runtime messages and validation state

Extend the dataflow execution/state model as necessary so validation agents can retrieve runtime information for each node.

Persist or otherwise make available the relevant execution messages associated with each node, including:
- Errors.
- Warnings.
- Informational logs.
- Validation messages.
- Execution status.
- Relevant output metadata and schema.

The Node Builder, Node Content Builder, Dataflow Builder, Node Researcher, and other validation-capable agents must be able to retrieve this information when diagnosing or correcting a node.

Avoid relying exclusively on transient UI console output.

---

## Node Researcher

Refine the Node Researcher into a true research agent with web-search capability.

Its purpose is to provide concise factual verification that other agents can invoke when generated behavior depends on external information.

Examples include:
- Verifying Socrata dataset IDs.
- Checking API documentation.
- Confirming endpoint syntax.
- Confirming parameter names.
- Verifying expected schemas or field names.
- Researching libraries or external services needed by a node.

The researcher should be reusable and chainable rather than implemented as isolated research logic inside each agent.

---

## Connection review happens after node validation

Connections should be reviewed as their own stage after the relevant nodes have been created and validated.

Display proposed edges vertically in a clear, inspectable list.

Each edge entry should show its source and target nodes adjacent to the connection information.

A compact dict-like representation is appropriate, for example:

`sourceNode → targetNode`

or conceptually:

`{ source: "Data Load", target: "Merge" }`

The user should be able to understand exactly which nodes are being connected before approving the edge.

Topology validation must run before an edge is applied.

---

## Merge-node detection

The connection stage must explicitly validate multi-input requirements.

If the desired topology would incorrectly produce:

`A → C`  
`B → C`

for a node `C` that cannot consume multiple independent inputs, the planner should resolve this into a valid topology such as:

`A → Merge`  
`B → Merge`  
`Merge → C`

Use the appropriate existing Merge node whenever available.

This should be identified during planning or connection validation, not after the resulting dataflow fails.

---

## Apply Plan remains available as an alternative

Keep the existing **Apply Plan** action, but make it an alternative to the default granular Simulation Mode.

**Apply Plan** should not revert to uncontrolled bulk generation.

Instead, it should automate the same validated workflow sequentially:

`Create node 1 → Solve → Execute → Validate → Create node 2 → Solve → Execute → Validate → ... → Validate connections`

It may reduce the number of manual approval clicks, but it must preserve:
- Per-node generation.
- Per-node Solve.
- Runtime validation.
- Error isolation.
- Self-correction.
- Correct ordering.
- Topology checks.

A failure in one node should stop or appropriately pause progression rather than blindly creating the remainder of an invalid graph.

---

## Final objective

The Dataflow Builder should produce a dataflow that becomes progressively valid as it is constructed.

The system should favor:

**plan → inspect → create → solve → execute → validate → approve**

over:

**plan → bulk-create → discover errors → repair**

The resulting orchestration must make every node and connection assessable, ensure agents have complete dataflow awareness, verify externally sourced information, expose runtime diagnostics to the agents, and prevent structurally invalid dataflows before they are materialized.