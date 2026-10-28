---
name: data-sources
description: >-
  Use this skill when node code reads data from a file, a Data Catalog dataset, a URL or an API,
  such as a node that loads data or fetches it. It gives the sources such code may read, in their
  order: a path the user typed, a catalog dataset through its loader line, a URL the runtime
  verified, a key-gated host through a saved key, and made-up data only when the user asked for it,
  and what to do when no source can be grounded.
license: MIT
compatibility: Written for Curio's agents, their tools and node code.
metadata:
  author: curio
  version: "1.0.0"
---
## Data sources

A node that reads data resolves its SOURCE before any code is written, in this order:

1. A file path the user typed in this conversation.
2. A Data Catalog dataset. Copy the row's `loader` line exactly, from catalog.search when the run has it, else as the run's dataflow context lists the dataset: `df = curio_load_data("<id>")`, which the sandbox resolves and reads by the dataset's format. Use `curio_data_path("<id>")` with your own reader only when the file needs one, such as a CSV with another delimiter.
3. An external source: only a URL the runtime has verified.
   - When `sourceGrounding.confirmedSource` is present, that IS the user's confirmed selection for this node: build from exactly those rows (a catalog row through `curio_data_path("<datasetId>")`, an external row from its exact url) and nothing else.
   - When "sourceGrounding" rides the run's inputs, fetch only its verifiedUrls and open only its listed paths. "urlEvidence" is what those endpoints actually answered: read it before changing the request.
   - Otherwise a chat delegates the "dataset.discover" capability with the intent, lets the user select and confirm a candidate from the card (do not propose in that same turn), then fetches the confirmed URL.
4. A key-gated endpoint whose host has a saved connection key, which the gate's refusal, the {{agent.name:agent.curio.dataset-finder}}'s `credential-gated` row or "sourceGrounding.availableSecrets" names. It is a grounded source when the code reaches the key ONLY through its `use` line, `api_key = curio_secret("<name>")`, which the sandbox resolves, and sends the value the way its `delivery` says (query:<param>, header:<Name>, or as the API documents when it is `code`). Never write a key literal or a key value into the code.
5. Data made up in the code: synthetic data ONLY when the user explicitly asked for made-up data in their own words: say so in the node's title.

Never invent a filename, never assume a file exists on disk, never write a URL from memory: the runtime probes every URL and refuses ungrounded content naming the literal: fix exactly that.

When "urlEvidence" shows the request was answered with a sign-in or "missing key" page, or the endpoint needs credentials the run was not given and no saved key covers its host, do not retry with other parameters. When no source can be grounded:

- in a chat, for a key-gated host without a saved key, name the host that needs one and stop; for any other source, ask the user for a path or URL instead of proposing a node;
- in a run that writes a node's content, reply with a one-line explanation naming exactly what is missing (for example, an API key for that host) instead of code.
