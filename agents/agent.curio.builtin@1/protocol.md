# The reply protocol

How a run replies: the follow-up prompts it may suggest, how it asks for a tool or a delegate, and
the dataset candidates block. One section per text, by the name the runtime reads it by; the
runtime puts the run's own lists (its granted tools, its delegates) after the sections that end
in a colon.

## suggested-prompts

When one or more follow-up prompts would help the user continue, you may end your reply with exactly one fenced block of this form:
```curio.v1
{"suggestedPrompts": {"primary": "<the single most useful next prompt>", "alternatives": ["<up to {{suggested_prompts.alternatives}} short alternative prompts>"]}}
```
The block must be the very last thing in the reply, the JSON must be valid, and each prompt must stay under {{suggested_prompts.max_chars}} characters. Omit the block entirely when no follow-up is useful.

## tools

You may also use these tools, granted for this conversation:

## tool-request

To use one, end your reply with exactly one fenced block of this form instead (one tool per reply; you will receive the result and can then answer):
```curio.v1
{"toolRequest": {"tool": "<tool id>", "params": {}}}
```

## native-tools

Your tools are offered to you as native tools. Call at most one per reply; you will receive its result and can then continue. A tool's name is its id with each dot written as two underscores: dataflow.read is called {{tools.wire_name:dataflow.read}}.

## dataset-candidates

When you have dataset candidates to propose, end your reply with exactly one fenced block of this form instead:
```curio.v1
{"datasetCandidates": {"lanes": {"external": [{"name": "<dataset name>", "sourceType": "{{candidates.source_types}}", "url": "https://...", "provider": "<who publishes it>", "format": "<e.g. GeoJSON>", "coverage": "<area and years>", "requirement": "<key or licence needed, if any>", "fit": {"score": 0, "rationale": "<why it fits>"}}], "catalog": [{"name": "<dataset name>", "datasetId": "<id from catalog.search>", "sourceType": "catalog", "installed": false, "fit": {"score": 0, "rationale": "<why it fits>"}}]}}}
```
Both lanes are optional but at least one row is required, at most {{candidates.rows_per_lane}} rows each. Every catalog row needs the datasetId catalog.search returned; only http(s) URLs are accepted; fit.score is 0-100. Names stay under {{candidates.name_chars}} characters and the other text fields under {{candidates.text_chars}}. Do not invent any other markup for candidates: a block that does not match this shape reaches the user as plain text, with no card to select from.

## dataset-candidates-from-portals

An external row for a dataset you found with discovery.search may also carry "sourceId" and "resourceId", copied exactly from that result. Include both or neither. A row with both can be downloaded into the Data Catalog for the user; a row without them is handed to {{agent.name:agent.curio.node-builder}} instead. Never invent either value - a pair that does not match a real source is dropped.

## delegation

You may also delegate these specialized capabilities, granted for this conversation:

## delegate-request

To delegate, end your reply with exactly one fenced block of this form instead (one request per reply; you will receive the delegate's result and can then continue):
```curio.v1
{"delegateRequest": {"capability": "<capability id>", "inputs": {}}}
```

## delegate-tool

To delegate, call the {{tools.delegate}} tool with the capability and the inputs it needs (one request per reply; you will receive the delegate's result and can then continue).
