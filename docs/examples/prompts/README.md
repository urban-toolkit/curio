# Prompt fixtures

Each file here pairs one natural-language **prompt** with one shipped example
dataflow and the answer key for it. Together they measure whether the Dataflow
Builder and the agents it delegates to can rebuild the dataflow a person asked
for.

- `<stem>.prompt.json` describes `docs/examples/<stem>.json`, one per curated
  example.
- `dataflows/<Name>.prompt.json` describes `docs/examples/dataflows/<Name>.json`,
  one per structural dataflow the end-to-end suite runs.

The schema is [`docs/schemas/example-prompt-fixture.v1.json`](../../schemas/example-prompt-fixture.v1.json).

## What the model sees

During an evaluation the agent receives **`prompt`** (and `context`, if the
fixture has one), and nothing else: never the example JSON, the node ids, the
node code, or the expected graph. A unit test enforces this: a prompt may not
contain a node or edge id, a canonical template id (`curio.builtin/...`), a line
of node code, a plan-grammar token, or a JSON object.

Human node-kind names are allowed. "Load it with `Data Loading` and chart it in
Vega-Lite" is how the walkthroughs read and how a person asks.

## Writing or editing a prompt

1. Read the example and its walkthrough. `python scripts/example_fixture_skeleton.py
   docs/examples/<stem>.json` prints the half that can be derived from the
   example (the digest, the declared dependencies and the canonical expected
   graph), so you write only the prompt beside a correct answer key.
2. Write what a person would type: the goal, the data by its catalog title (or
   by its repo-relative path, for an example that reads a committed file: a path
   the user typed is a source the grounding gate accepts), and the shape of the
   result. Say what you want to see, not how many nodes it takes.
3. A model may draft the prompt from the example and its walkthrough. A person
   then reviews it: `review.status` starts at `pending-owner-review`, and only a
   person moves it to `approved`. The deterministic suite ignores the review,
   the live report labels it, and `agent_eval export` leaves out anything that
   is not approved.
4. Tests never generate a prompt or an expected answer at run time.

## Fields worth understanding

| Field | What it does |
|---|---|
| `source.sha256` | Drift guard. Editing an example fails the suite until someone re-reviews this fixture. |
| `expected` | The example, normalized: canonical template ids, roles, edges with `kind` and merge `slot`, and the sources the code reads. The suite recomputes it and compares, so it is never edited by hand. |
| `required` | The dependencies, copied from the example's own `dataflow.datasets` and `dataflow.packages`, plus `paths` for a committed file the prompt names. |
| `intents` | Per-node meaning checks: words the reconstructed node's intent must mention, and the output kind Solve should record. |
| `capability.needs` | What this fixture needs beyond plain offline reconstruction. Two of them are package routes: `package-enlist:templates` (the plan cannot name the template until the package is enlisted, as in example 10) and `package-enlist:dependencies` (every node is a built-in template, but the code imports libraries an installed package's manifest owns, as in example 09). Neither is a reason to author a new package. |
| `capability.skip` | Every exclusion, with a written reason. |
| `split` | `train`, `validation` or `heldout`: the split `agent_eval export` writes a fixture under. |
