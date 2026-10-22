# Delegate contracts

What a delegated run is told to reply with, in its inputs. `build-request` and `notes-reply` are
each one JSON object, which the delegate receives as its `buildRequestContract` and
`notesReplyContract`; `dataset-candidates` is the rule a delegated Dataset Finder answers to,
which the runtime gives it with the dataset candidates block of `protocol.md`.

## build-request

```json
{
  "reply": "Reply with ONE JSON object of exactly this shape (optionally inside a ```json fence), nothing after it. Do NOT invent other keys: there is no 'package', 'behaviors', or 'behaviorKey' key.",
  "insteadOfAuthoring": "When one of inputs.existingPackages already satisfies the need, author NOTHING and reply with ONE JSON object of exactly this shape instead of a draft: {\"reuseExisting\": {\"dirName\": \"<its dirName>\", \"reason\": \"<one line: what it already does>\"}}. That is a complete, successful answer: the caller acts on it (enlisting the package if it is not yet in the project). Prefer extending an existing package (mode 'extend') over creating a near-duplicate.",
  "shape": {
    "mode": "create | extend",
    "justification": "<the closest existing templates you considered and why each is inadequate: needed when the draft adds a template>",
    "baseDigest": "<64-hex digest of the installed target (extend only)>",
    "manifest": {
      "id": "reverse-DNS: two or more dot-separated lowercase segments, e.g. 'curio.notes'. Single-segment ids are invalid",
      "version": "1.0.0",
      "name": "<display name>",
      "publisher": "<author>",
      "description": "<one line>",
      "license": "MIT",
      "compatibility": {
        "curioRuntime": ">=0.5.0",
        "major": 1
      },
      "permissions": [],
      "dependencies": {
        "packages": {},
        "python": {},
        "js": {}
      },
      "templates": [
        {
          "id": "<kebab-case template id>",
          "label": "<display label>",
          "category": "visualization",
          "engine": "python | javascript",
          "editor": "code | widgets | grammar | none",
          "behavior": "<the behavior key your source registers (custom looks only)>",
          "hasCode": false,
          "hasWidgets": false,
          "hasGrammar": false,
          "inputPorts": [],
          "outputPorts": [],
          "backendHandler": "<declared backend handler name this template's Run invokes (backend templates only)>"
        }
      ],
      "backend": {
        "entry": "backend/handler.py",
        "handlers": [
          {
            "name": "<a name matching {{backend.handler_pattern}}>",
            "timeoutClass": "{{backend.timeout_class_choices}}"
          }
        ]
      }
    },
    "files": {
      "sources/<name>.tsx": {
        "text": "<complete file body>"
      }
    },
    "behaviorEntries": ["sources/<name>.tsx"],
    "previewTemplates": ["<each template id with a custom behavior>"],
    "nodes": [
      {
        "templateId": "<template id>",
        "title": "<node title>",
        "content": "<the fixed note/body text>",
        "appearance": {
          "backgroundColor": "{{note.palette_choices}}|#rrggbb"
        }
      }
    ]
  },
  "rules": [
    "every template the draft adds (all of a create's, the new ones of an extend) needs the top-level justification, which the user reads first on the review card, and a label no existing template has: a template that already does the job is reused (insteadOfAuthoring), never drafted again",
    "a presentation-only template is engine 'javascript', editor 'none', hasCode false, empty ports",
    "the behavior source registers EXACTLY the template's behavior key: window.curio.registerBehavior(key, (data, nodeState) => ({ contentComponent: <React element> })). Import react normally, render React elements only, never raw HTML",
    "field contract: the note text arrives as data.code (data.content is an equivalent alias), the title as data.title, the per-instance color as data.appearance.backgroundColor (also nodeState.appearance.backgroundColor). Read THESE fields, never invented ones",
    "prefer ZERO JS dependencies: write small rendering logic yourself",
    "the caller's inputs.notes ARE the requested nodes: copy each {title, content, color} into nodes[] VERBATIM. Never invent placeholder content, never leave content empty when the caller supplied findings (the runtime enforces this reconciliation)"
  ]
}
```

## notes-reply

```json
{
  "reply": "Reply with ONE JSON object of exactly this shape (optionally inside a ```json fence), nothing after it.",
  "shape": {
    "answer": "<the prose answer to the question (always present)>",
    "nodeType": "<one 'id' from inputs.notesTemplates (omit when that list is empty)>",
    "notes": [
      {
        "title": "<short note title>",
        "content": "<the finding as clean markdown: bold fact labels, '- ' bullets, [source](https://...) links>",
        "color": "{{note.palette_choices}}|#rrggbb"
      }
    ]
  },
  "rules": [
    "compose findings ONLY from inputs.searchResults. When it carries an 'error', say in 'answer' that search was unavailable and reply with an empty notes list; NEVER invent findings from memory",
    "the reference row (dev/90 A13): the FIRST note carries the user's question verbatim (title 'Question', color yellow); then one green note per answer with a subject title and every web-gathered fact linked to its source",
    "an empty notes list is valid when nothing should be placed (no template installed, or no findings)"
  ]
}
```

## dataset-candidates

You are running as a delegate without tools. The `catalog` input IS the project's Data Catalog (catalog.search was run for you): catalog-lane rows must come ONLY from it, quoting each row's id as datasetId. Any other id is dropped. External rows are suggestions the runtime will probe; do not claim verification. Reply with the datasetCandidates block described below and a one-line summary; nothing else.
