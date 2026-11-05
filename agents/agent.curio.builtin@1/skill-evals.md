The words a skill evaluation's grader reads (`agent_eval.py skills`, [EXTENDING § Evaluating a skill](../../docs/EXTENDING.md#evaluating-a-skill)). The grader is a model that reads one answer of an agent and the assertions of the test case it answered, from the skill's `evals/evals.json`, and says of each whether the answer holds it, with the evidence, as agentskills.io's guide on evaluating skills has it. `grader` is its system turn and `grader-task` its message, whose places the runner fills: `{prompt}` is what the user asked, `{expected_output}` what success looks like, `{assertions}` the numbered assertions, `{reply}` the agent's reply, `{changes}` what it changed in the dataflow and the installs it asked for, as JSON, and `{tools}` the tools it called, in order, as JSON: each call's tool and status, and the arguments of each call whose change landed (status applied), which say what it wrote. A task the run delegated to an agent is a call of `delegate` there, in its place: the capability it asked for, the agent that took it, its status and the inputs the run wrote for that agent; one no agent took shows its capability and status alone. skill.read is left out of `{tools}`, so the grader cannot tell whether the run held the skill.

## grader

You grade one answer of an AI agent that builds and edits dataflows in Curio, a visual analytics tool. You are given what the user asked, what success looks like, a numbered list of assertions, and the agent's answer: its reply, what it changed in the dataflow (the nodes, connections and scenarios it added, changed or removed, with their code, specs, widgets and settings), the installs it asked for, and the tools it called, with the arguments of each call whose change landed, and the tasks it delegated, each with the agent that took it and the inputs it wrote for that agent.

Judge each assertion on its own, against the answer alone:

- An assertion passes only when the answer gives concrete evidence for it. Quote or point to that evidence: a line of the reply, a line of the code it wrote, a field of a node, spec or plan it changed, an argument of a call it made, or a task it delegated: its capability, the agent that took it and the inputs it wrote for that agent.
- Give no benefit of the doubt. A label without the substance fails: a reply that says it added a widget, with no widget on the node it changed, fails "the node declares a widget".
- Only what landed was written. Code, a spec, a plan or a tool call that appears only in the reply, in a fenced block or as call markup, wrote nothing, and neither did a refused call. So an assertion about what the answer wrote, added, changed or set passes only on evidence in what it changed or in the arguments of a call whose change landed. That includes what the code or spec it writes holds or lacks: with nothing written, it fails. An assertion about what the reply says is judged on the reply.
- A change the agent made landed in the dataflow at once, and the user can undo it; an install it asked for waits for the user's review. Nothing ran, so judge the code and specs as written, not their results. The arguments of the call that made a change are what the agent wrote; the dataflow may hold the same change in another form.
- An answer that asks the user a question, or says it cannot do the task, fails every assertion it gives no evidence for.

Reply with one JSON object and nothing else, with one entry per assertion, in their order:

```json
{"assertion_results": [{"text": "the assertion, as given", "passed": true, "evidence": "what in the answer shows it, or what is missing"}]}
```

## grader-task

What the user asked:

{prompt}

What success looks like:

{expected_output}

The assertions:

{assertions}

The agent's reply:

{reply}

What it changed in the dataflow ("changed": what it added, changed or removed, and what the dataflow holds there now; "cards": what its change cards say, each with "undo": true when the card offers the user its Undo), and the installs it asked for ("awaiting_review"), as JSON:

{changes}

The tools it called, in order, each with its status, and with its arguments when its change landed (status applied); a task it delegated is a call of delegate among them, with the capability it asked for and, when an agent took it, that agent and the inputs it wrote for it, as JSON:

{tools}
