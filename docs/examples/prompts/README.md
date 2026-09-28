# Prompt fixtures — measuring the agents against these examples

Each file here pairs one natural-language **prompt** with one shipped example
dataflow and the answer key for it. Together they are how Curio measures
whether the Dataflow Builder and its delegated agents can *reconstruct* a
dataflow someone asked for, rather than whether a saved dataflow still works
(memo `dev/121`).

- `<stem>.prompt.json` describes `docs/examples/<stem>.json` (the 11 curated
  examples).
- `dataflows/<Name>.prompt.json` describes `docs/examples/dataflows/<Name>.json`
  (the 20 legacy structural dataflows).

The schema is [`docs/schemas/example-prompt-fixture.v1.json`](../../schemas/example-prompt-fixture.v1.json).

## What the model sees, and what it must not

During an evaluation the agent receives **`prompt`** (and `context`, if the
fixture has one). Nothing else. It never receives the example JSON, the node
ids, the node code, or the expected graph — that would measure transcription,
not reconstruction. A unit test enforces this: a prompt may not contain a node
or edge id, a canonical template id (`curio.builtin/...`), a line of node code,
a plan-grammar token, or a JSON object.

Human node-kind names are deliberately allowed. "Load it with `Data Loading`
and chart it in Vega-Lite" is how the walkthroughs read and how a person
actually asks; refusing those words would make the prompts unnatural without
hiding anything the roster does not already tell the agent at run time.

## Writing or editing a prompt

1. Read the example and its walkthrough. `python scripts/example_fixture_skeleton.py
   docs/examples/<stem>.json` prints the machine-derivable half — the digest,
   the declared dependencies and the canonical expected graph — so you write
   only the prompt beside a correct answer key.
2. Write what a person would type: the goal, the data by its catalog title (or
   by the literal repo-relative path, for the legacy examples that read a
   committed file — a typed path is a source the grounding gate accepts,
   `DEC-072`), and the shape of the result. Say what you want to see, not how
   many nodes it takes.
3. A model may draft the prompt from the example and its walkthrough as a
   one-time authoring aid. It is then **reviewed by a person** and committed:
   `review.status` starts at `pending-owner-review` and only a human moves it
   to `approved`. The deterministic suite does not care about the review; the
   live report labels it; the fine-tuning export refuses anything unapproved.
4. Tests never generate a prompt or an expected answer at run time.

## Fields worth understanding

| Field | What it does |
|---|---|
| `source.sha256` | Drift guard. Editing an example fails the suite until someone re-reviews this fixture. |
| `expected` | The example, normalized: canonical template ids, roles, edges with `kind` and merge `slot`, and the sources the code reads. Recomputed and compared by the suite — never hand-edited into disagreement. |
| `required` | The dependency source of truth, copied from the example's own `dataflow.datasets` and `dataflow.packages`, plus `paths` for a committed file the prompt names. |
| `intents` | Per-node meaning checks: words the reconstructed node's intent must mention, and the output kind Solve should record. |
| `capability.needs` | What this fixture needs that plain offline reconstruction does not. Two of them are different package routes: `package-enlist:templates` (the plan cannot even name the template until the package is enlisted — example 10) and `package-enlist:dependencies` (every node is a builtin template, but the code imports libraries an installed package's manifest owns — example 09). Neither is a reason to author a new package. |
| `capability.skip` | Every exclusion, with a written reason. Nothing is dropped silently. |
| `split` | `train` / `validation` / `heldout` for a future fine-tuning export. Held-out fixtures are never training data. |

## The capability gap you will see first

Eight fixtures need `interaction-edge`: examples 07, 08 and 09, plus
`Interaction_Autark`, `Interaction_Vega`, `Interaction_Vega_Autark`,
`Interaction_Vega_Simple` and `Regression`. A brushable chart that highlights
its map is a **bidirectional** link, and the plan contract on this branch
carries only `from`, `to` and `toHandle` — so no plan can produce those edges
yet. The harness reports that as a named capability gap. It does **not** delete
the edges from the expected graph to make a test pass: the expected graph is
what the user asked for, and the gap is the finding.
