# Contributing to Curio

This guide is for students getting their first taste of open-source work and for developers who already know their way around a codebase. It covers how Curio is put together, how to get it running, and where the useful contributions tend to be.

## Table of Contents

* [Why Contribute](#why-contribute)
* [Technology Overview](#technology-overview)
* [Repository Structure](#repository-structure)
* [Installation Options](#installation-options)
  * [Via pip (lightweight setup)](#via-pip-lightweight-setup)
  * [From GitHub (for development)](#from-github-for-development)
* [Suggested Contribution Paths](#suggested-contribution-paths)
  * [Testing and Debugging](#testing-and-debugging)
  * [Developing Dataflow Nodes](#developing-dataflow-nodes)
  * [Example Workflows](#example-workflows)
  * [Documentation](#documentation)
  * [Community and Support](#community-and-support)
* [Getting Started (Step-by-Step)](#getting-started-step-by-step)
* [Running Tests](#running-tests)
  * [TL;DR](#tldr)
  * [One-Time Setup](#one-time-setup)
  * [Backend and Sandbox Tests](#backend-and-sandbox-tests)
  * [Agent Reconstruction Tests](#agent-reconstruction-tests)
  * [Frontend Unit Tests](#frontend-unit-tests)
  * [Frontend E2E Tests](#frontend-e2e-tests)
  * [Database Migrations](#database-migrations)
  * [Agent Text](#agent-text)
  * [Shared Constants](#shared-constants)
  * [Vendored Autark Schema](#vendored-autark-schema)
* [Organizing Contributions](#organizing-contributions)
  * [Defining the Scope of a Pull Request](#defining-the-scope-of-a-pull-request)
  * [Pull Request Template](#pull-request-template)
  * [Issue Template](#issue-template)
* [Advice for Students](#advice-for-students)
* [Need Help](#need-help)

## Why Contribute

Contributing to Curio offers the opportunity to:

* Gain experience with a modern tech stack used in both research and industry
* Understand how visual analytics systems are built from the ground up
* Collaborate with a team of researchers
* Build a public portfolio of meaningful contributions (code, documentation, testing)
* Engage with real-world data, such as urban mobility, accessibility, or environmental datasets

## Technology Overview

| Component | Technology                             | Function                                                             |
| --------- | -------------------------------------- | -------------------------------------------------------------------- |
| Backend   | Python, Flask                          | REST API for managing users, workflows, and provenance               |
| Frontend  | React, TypeScript, Autark, Vega-Lite   | Browser-based interface for authoring and interacting with dataflows |
| Execution | Python sandbox (multiprocess)          | Secure module for executing user code                                |
| DevOps    | Docker, Docker Compose, GitHub Actions | Containerization, deployment, and CI/CD                              |
| Packaging | PyPI (`utk-curio`)                     | Distributes the CLI and backend/frontend bundle                      |

## Repository Structure

The codebase follows a modular structure under the `utk_curio/` directory. This separation supports clean boundaries between backend, frontend, and execution logic.

```
curio/
├── utk_curio/
│   ├── backend/                            # Manages database access and user authentication
│   │   ├── app/agents/domain/contracts.py  # The contracts the code and the agents agree on, and the prompt fields (see Agent Text)
│   │   ├── app/agents/schemas/             # The vendored Autark grammar schema (see Vendored Autark Schema)
│   │   ├── app/discovery/                  # The Discovery Catalog: portal, storage, service and model sources
│   │   ├── app/packages/                   # The Node and Model Catalogs: node packages, and model packages with their weights
│   │   ├── migrations/                     # Alembic migrations
│   │   └── tests/                          # pytest files for backend (+ test_frontend/ for Playwright E2E)
│   ├── sandbox/                            # Executes user Python code in a secure environment
│   │   └── tests/                          # unittest files for sandbox
│   └── frontend/                           # All frontend logic
│       └── urban-workflows/                # Main Curio interface for dataflow editing
│           └── src/
│               ├── components/             # React components and CSS
│               ├── contracts/              # Constants shared with the backend, one JSON file each (see Shared Constants)
│               └── tests/                  # Jest unit tests
│
├── curio.py                        # CLI entry point for running and managing all services
├── agents/                         # Everything the agents read: one directory per agent, a manifest.json and its prompts/, and the base entry agent.curio.builtin@1 with the pages they share
├── packages/                       # The shared node catalog: one directory per node package
├── datasets/                       # The shared Data Catalog: datasets published on this install
├── discovery/                      # The Discovery Catalog: one manifest per portal or storage source this install can reach
├── scripts/                        # test.sh, clean.sh, new_package.py, regen_integrity.py, sync_autk_schema.py
├── docs/                           # Documentation, usage guides, and examples
│   └── examples/dataflows/         # Dataflow JSONs used by the E2E suite
└── requirements.txt                # Curio framework dependencies (data-ops libs live in each package's manifest.dependencies.python)
```

To build a node of your own, start with [AUTHORING-NODES.md](AUTHORING-NODES.md), a task-ordered walkthrough from a clone to a shareable package. For how packages are stored, versioned, forked, and published, see [NODE-CATALOG.md](NODE-CATALOG.md). For how datasets are published, installed, and consumed, see [DATA-CATALOG.md](DATA-CATALOG.md). For the data portals an install can download from, see [DISCOVERY-CATALOG.md](DISCOVERY-CATALOG.md). For how the system is structured (nodes, data flow, execution pipeline, provenance) see [ARCHITECTURE.md](ARCHITECTURE.md).

## Installation Options

### Via pip (lightweight setup)

```bash
pip install utk-curio
curio start
```

This installs the CLI and a pre-built version of the frontend. You won’t be able to modify or rebuild the UI from this setup. Twelve catalog files are not in the package: Curio downloads each from GitHub the first time it reads it ([Installation from pip](USAGE.md#installation-from-pip)).

### From GitHub (for development)

```bash
git clone https://github.com/urban-toolkit/curio.git
cd curio
python curio.py start           # serves the built bundle; builds it once on a fresh clone
python curio.py start --dev     # webpack dev server instead, with hot reload
```

Add `--dev` whenever you are editing anything under `utk_curio/frontend/`, or your changes will not show up until you rebuild. Without it Curio serves the production bundle from `dist/`, which loads much faster but is a build artifact.

Refer to [USAGE.md](USAGE.md) for Docker instructions and frontend build steps.

## Suggested Contribution Paths

### Testing and Debugging

* Write or improve `pytest` tests in `backend/tests` and `sandbox/tests`
* Reproduce and resolve issues from GitHub
* Extend test coverage for edge cases

### Developing Dataflow Nodes

* Add new analytic operations as reusable nodes
* Improve UI and metadata descriptions

### Example Workflows

* Create dataflow examples using public datasets
* Annotate dataflows to serve as tutorials
* Contribute to the `examples/` directory

A new dataflow in `docs/examples/` or `docs/examples/dataflows/` ships, so list it in
[`agents/agent.curio.builtin@1/examples.md`](../agents/agent.curio.builtin@1/examples.md): under
"Used" with one line on what it shows when agents should learn from it, or under
"Not used" with the reason. The line leaves out the city, topic, node types and
datasets: they are read from the file. `test_prompt_references.py` fails until the
dataflow is listed, and checks every "Used" dataflow the way it checks the prompts.

The Projects page lists a numbered dataflow in `docs/examples/` under Examples. To
list it under Use cases, add its key, the file name without `.json`, to `useCases` in
`docs/examples/use-cases.json`, the index beside the dataflows, and update the list
`test_use_cases.py` and `test_categories.py` pin. Write no source into the dataflow
file: a dataflow's source comes from its id, so a copy of it stays the user's own.

### Documentation

* Write developer setup instructions or onboarding checklists
* Add usage diagrams, screenshots, or schema explanations
* Contribute inline documentation and docstrings

The six catalog guides (`NODE-CATALOG.md`, `DATA-CATALOG.md`, `MODEL-CATALOG.md`, `AGENT-CATALOG.md`, `DISCOVERY-CATALOG.md`, `SCENARIO-CATALOG.md`) share one outline, so a reader who knows one knows where to look in the others: **1. What is the X Catalog?** (Concept, What ships with Curio, Storage layers), **2. Surfaces and workflows** (Action matrix, Workflows), **3. Using X in a dataflow**, the catalog's own parts, then **Importing, publishing, and sharing**, **The manifest**, **Operator notes**, and **See also**. Keep them at user level: name UI labels exactly as the app shows them, and leave routes, module names, internal mechanism and design rationale to [ARCHITECTURE.md](ARCHITECTURE.md) and code comments.

### Community and Support

* Test Curio across platforms (Windows, macOS, Linux)
* Suggest improvements to onboarding and usability

## Getting Started (Step-by-Step)

1. **Fork and clone the repository**

To fork the repository, visit the [Curio GitHub page](https://github.com/urban-toolkit/curio) and click the "Fork" button in the upper-right corner (for more details see GitHub's [Forking a repo](https://docs.github.com/en/get-started/quickstart/fork-a-repo)). This will create a personal copy of the repository under your GitHub account.

After forking:

1. Clone your fork to your local machine:

   ```bash
   git clone https://github.com/YOUR_USERNAME/curio.git
   cd curio
   ```
2. Set the original repository as an upstream remote so you can keep your fork up to date:

   ```bash
   git remote add upstream https://github.com/urban-toolkit/curio.git
   ```

3. **Set up a virtual environment**

   ```bash
   conda create -n curio python=3.12
   conda activate curio
   pip install -r requirements.txt
   ```

4. **Run the system**

   ```bash
   python curio.py start --dev
   ```

   `--dev` serves the frontend through the webpack dev server so source edits
   reload. Drop it to serve the built bundle instead.

5. **Create a feature branch**

   ```bash
   git checkout -b my-feature
   ```

6. **Make your changes and commit when you are done**

   ```bash
   git add .
   git commit -m "Add: feature description"
   git push origin my-feature
   ```

7. **Submit a pull request**

   Open a PR on GitHub with a detailed description and link to relevant issues. **When you create a PR, make sure you create a PR selecting the branch of the upstream repository you'd like to merge changes into (usually urban-toolkit/curio main).**

## Running Tests

Before submitting a pull request, run the relevant test suites to confirm your changes don't introduce regressions.

### TL;DR

One command starts all Curio services, runs unit tests and Playwright E2E tests, then shuts everything down:

```bash
python curio.py test
```

It first deletes the checkout's `.curio/` folder, where local projects and data live, along with the frontend's `node_modules/`, `dist/` and `build/`, so keep work you care about in another clone. `--use-existing` skips that cleanup and uses servers that are already running, started with `python curio.py start --deploy --testing --with-examples`.

Common shortcuts:

```bash
# servers already running, unit tests only (backend + sandbox + jest)
python curio.py test unit --use-existing

# one suite: all | unit | backend | sandbox | jest | e2e
python curio.py test backend

# watch the browser, specific workflows only
python curio.py test e2e --use-existing --headed --workflows vega.json,regression.json

# E2E on 4 xdist workers, one backend+sandbox pair each (see test_frontend/README.md, "Parallel")
python curio.py test e2e --parallel 4
```

See `python curio.py test --help` for all options, or read the sections below for
more detail. The command is a front end for `./scripts/test.sh`, which CI calls
directly and which accepts its own flags (`--unit-only`, `--e2e-only`, ...)
if you prefer to run it yourself.

### One-Time Setup

Install the Playwright browser once (use the same Python/venv you use for pytest):

```bash
playwright install chromium
# or: python -m playwright install chromium
```

### Backend and Sandbox Tests

```bash
pytest utk_curio/backend/tests/ --ignore=utk_curio/backend/tests/test_frontend
pytest utk_curio/sandbox/tests/
```

#### Tests do not reach the network

The backend suite refuses outbound connections. Loopback is allowed, because the
sandbox, the backend health polls and the Playwright stack all need it; anything
else raises `NetworkAccessDenied` naming the host it blocked. The guard lives in
`utk_curio/backend/tests/netguard.py`, which explains how it works and what it
cannot cover.

A test that talks to a third party fails when that third party is slow, down, or
answers differently than it did yesterday. Rather than trust every author to
remember to inject a fake, the suite makes forgetting a loud, immediate failure.
If you hit it, the fix is almost always to inject a fake transport -- most
network-touching code in this repo already takes one (`egress.fetch`'s
`request_fn` and `resolver`, `RegistryFetcher`, `DiscoveryTransport`).

Two markers opt out, and they mean different things:

| Marker | Runs by default | Use it for |
|---|---|---|
| `@pytest.mark.contract` | **yes**, including CI | Checking that a third party's response *shape* still matches what our parser expects. Must skip -- never fail -- when the endpoint is unreachable, returns a non-2xx, or answers something other than the expected content type. The only permitted failure is a successful response whose shape changed. |
| `@pytest.mark.externalapi` | no, needs `--longrun` | Anything else that genuinely needs the network. |

Writing a contract test that can fail for a reason outside our control puts a
third party in the critical path of every PR, which is the problem the guard
exists to solve. Skip generously; a contract test that skips has cost nothing,
and its skip reason is printed under `pytest -v`.

### Agent Reconstruction Tests

Separate from the suites above, these ask whether a *model* can rebuild one of
the shipped example dataflows from a plain-language prompt. Every example has a
reviewed prompt fixture under `docs/examples/prompts/`; the deterministic tiers
run offline in seconds and need no stack:

```bash
pytest utk_curio/backend/tests/test_agents/test_example_fixtures.py \
       utk_curio/backend/tests/test_agents/test_reconstruction_canonical.py \
       utk_curio/backend/tests/test_agents/test_reconstruction_scoring.py \
       utk_curio/backend/tests/test_agents/test_evaluation_policy.py \
       utk_curio/backend/tests/test_agents/test_example_reconstruction.py

python -m utk_curio.tools.agent_eval list      # the fixtures and their splits
```

A fixture pins its example's digest, so editing an example fails these tests
until someone re-reads the prompt and the expected graph and moves the pin. The
browser tier is opt-in with the other example-dependent tests
(`--with-examples`). A live-model evaluation needs two opt-ins, and it writes a
report; it neither passes nor fails:

```bash
export CURIO_EVAL_LIVE=1
python -m utk_curio.tools.agent_eval run --token "$CURIO_EVAL_TOKEN" --tier T0
```

See [ARCHITECTURE.md](ARCHITECTURE.md#evaluation) for how an evaluation runs
and what the score means.

**Saving a project** goes through a guard: every write of a spec bumps a
counter at the one chokepoint that writes it, a client sends the revision it
last synced with as `baseRevision`, and a save whose basis is stale **and**
which would delete a node, an edge or a node's code that exists on disk is
refused with 409. A caller that sends no basis is not checked. If you add a path
that writes a project spec, you get the counter for free; if you add a client
that saves one, send the basis.

The page gives up on a save after 2 minutes (`SAVE_TIMEOUT_MS` in
`src/api/projectsApi.ts`), and the server may still apply it later. So a canvas
save also sends its tab's id and a number one higher than the tab's last save
(`saveTab` and `saveNumber`, from `src/api/saveOrder.ts`), and a save numbered
lower than one already applied from its tab is refused with 409 before anything
is written. A save without them is not checked.

```bash
pytest utk_curio/backend/tests/test_projects/test_save_concurrency.py \
       utk_curio/backend/tests/test_projects/test_routes.py \
       utk_curio/backend/tests/test_datasets/test_save_order.py
```

### Frontend Unit Tests

The frontend uses Jest and React Testing Library for component and TypeScript unit tests.

```bash
cd utk_curio/frontend/urban-workflows
npm test -- --watchAll=false
```

Tests live under `src/tests/` and mirror the structure of `src/components/`. See [utk_curio/frontend/urban-workflows/src/tests/README.md](../utk_curio/frontend/urban-workflows/src/tests/README.md) for guidelines on writing and organizing tests.

The project uses **Node 26**. Jest needs a Node that can `require()` an ES module (transitive dep `html-encoding-sniffer@6` does), and older Node fails every suite with `ERR_REQUIRE_ESM`. Install it into the `curio` conda env with `conda install -c conda-forge nodejs=26` and run `conda activate curio` before `npm test`, or use a system install of Node 26 (`.nvmrc` and `.node-version` pin it for nvm/fnm/asdf). A checkout whose `node_modules` was installed under an older Node reinstalls itself on the next `curio.py start` -- the launcher stamps the installing major into `node_modules/.curio-node-major` and wipes the tree when it changes, so there is no folder to delete by hand.

### Frontend E2E Tests

The frontend tests use Playwright to upload workflow JSON files into the Curio UI and verify the ReactFlow canvas renders correctly.

```bash
# full suite
pytest utk_curio/backend/tests/test_frontend/

# watch the browser while tests run
pytest utk_curio/backend/tests/test_frontend/ --headed

# use servers already started with --deploy --testing --with-examples (e.g. docker-compose.ci.yml)
CURIO_E2E_USE_EXISTING=1 pytest utk_curio/backend/tests/test_frontend/
```

Run only specific workflows by setting `CURIO_E2E_WORKFLOWS` (comma-separated basenames):

```bash
CURIO_E2E_WORKFLOWS=vega.json,regression.json pytest utk_curio/backend/tests/test_frontend/test_workflows.py
```

Preview which tests will run without executing them:

```bash
pytest --collect-only utk_curio/backend/tests/test_frontend/test_workflows.py
```

Run a single workflow test:

```bash
# one workflow, one test method
pytest utk_curio/backend/tests/test_frontend/test_workflows.py::TestWorkflowCanvas::test_node_and_edge_count[vega.json]

# all checks for one workflow
pytest utk_curio/backend/tests/test_frontend/test_workflows.py -k "vega.json"
```

**Test matrix.** Each workflow runs four checks:

| Test | What it verifies |
|---|---|
| `test_node_and_edge_count` | Canvas has the exact node/edge counts from the JSON |
| `test_node_positions` | Relative x-ordering of nodes is preserved |
| `test_node_type_and_content` | Correct editor widget per node category (code, grammar, datapool, passive) |
| `test_node_execution` | Nodes execute correctly and produce the expected output |

**Environment variables:**

| Variable | Purpose |
|---|---|
| `CURIO_E2E_WORKFLOWS` | Comma-separated workflow basenames to run (default: all) |
| `CURIO_E2E_USE_EXISTING` | Set to `1` to skip server startup and use running servers |
| `CURIO_E2E_HOST` | Host for existing servers (default: `localhost`) |
| `CURIO_E2E_BACKEND_PORT` | Backend port for existing servers (default: `5002`) |
| `CURIO_E2E_SANDBOX_PORT` | Sandbox port for existing servers (default: `2000`) |
| `CURIO_E2E_FRONTEND_PORT` | Frontend port for existing servers (default: `8080`) |

### Database Migrations

If you modify any database model, generate and apply a migration before running tests:

```bash
# generate a new migration after updating a model
FLASK_APP=server.py flask db migrate -m "Migration Name"

# apply any pending migrations
FLASK_APP=server.py flask db upgrade
```

### Agent Text

Everything the agents read is hand-written Markdown in `agents/` and
`skills/`: each agent's prompts in its folder, the pages they share in the
base entry, [`agents/agent.curio.builtin@1/`](../agents/agent.curio.builtin@1/)
(the preamble, the worked examples' index and the rules prompts include), and
Curio's skills, [`skills/`](../skills/), one per feature of Curio: the
preamble places the core three, and each agent's manifest names the others
its runs read. A new feature, such as a built-in template, a function node
code calls or a kind of chip, gets its lines in a skill in the same change:
`test_feature_skills.py` fails while one is in no skill, and
`test_skill_listing.py` while a skill reaches no agent.
[EXTENDING §9](EXTENDING.md#9-writing-a-skill) says how to write a skill. Where a
page, prompt or skill states a fact the code owns (an agent's name, a
template's label, the Trill block), it holds a marker, `{{field}}`, which the
backend fills from `contracts.PROMPT_FIELDS` when it starts;
`{{include:<path>}}` puts another page in its place, and `{{skill:<name>}}` a
skill's body. To change agent text, edit its file and restart the
backend, or run `python curio.py start --dev`, which renders a file again on
every read. The base entry's README walks through it. The backend suite
renders every file (`test_agent_text.py`) and fails on a marker no field
defines. See [ARCHITECTURE.md, Agent text](ARCHITECTURE.md#agent-text).

What a check tells a model when it refuses or corrects what the model wrote
is a message of the base entry's `messages.md`, one section per message, which
the check reads by its id: `agent_text.message("tool-round.not-granted", tool=name)`. A
new refusal is a new section and the call that says it, and a value only the
run knows, such as a node's id or the problems found, is a `{name}` place the
call fills. A message is text a check addresses to the model about what the
model wrote: a refusal, a correction, or the notes its next attempt is given,
even when a card shows it too. A feature's own record or data is no message,
even when a run reads it later: an error on Play, the run journal's reason, a
probe's verdict and a candidate's download steps, the reason an Apply or a
card gives, an HTTP error, a chat record, the command line's and the logs'
text stay with their feature, in Python. `test_messages.py` checks every call
against the page, and `test_prose_guard.py` fails on a string in
`utk_curio/`'s Python whose words run past 200 characters unless it is a
message to users or code; a new one of those goes in the test's `USERS` or
`CODE` list, with who reads it.

### Shared Constants

The vocabularies and tables the frontend and the backend both read are JSON
files in `utk_curio/frontend/urban-workflows/src/contracts/`: why a render drew
nothing, why a repair loop stopped, the agent categories, a note's colors, the
Autark facts a grammar node uses, and the starter ladders, dtype roles, Vega-Lite
`$schema` URL and image column rule of the visualization nodes. The frontend
imports each file and the backend reads it
(`utk_curio/common/shared_constants.py`), so a change is one edit to the file,
with nothing to run. An object that names one key twice is refused.

To add, remove or reorder a starter rule, edit its ladder in `visDefaults.json`
and add or remove its builder in `vegaDefaultSpec.ts` or `autkDefaultSpec.ts`,
keyed by the rule's id. `inputTableName` and `autkOneViewProblem` are code over
`autkGrammar.json` on both sides, in `contracts/autkGrammar.ts` and
`contracts.py`; a change to either goes into both, with a case for it in
`autkGrammar.cases.json`, which Jest and the backend suite both run. See
[ARCHITECTURE.md, Shared Constants](ARCHITECTURE.md#shared-constants).

### Vendored Autark Schema

Autark documents are validated against the JSON Schema that autk-grammar
publishes. `utk_curio/backend/app/agents/schemas/autk-grammar.v1.json` is a
byte-for-byte copy of the released file, and `autk-grammar.v1.source.json`
records its version and digest. To move to a new release:

```bash
# vendor the schema from the release on npm
python scripts/sync_autk_schema.py --version <version>
```

`--from PATH` vendors a local build of that version instead.
`test_autk_schema_vendored.py` checks the copy against its record in the
backend suite, and the weekly `autk-schema` workflow runs
`python scripts/sync_autk_schema.py --check` against npm. A release that adds
or drops a top-level family needs it in `families` of
`src/contracts/autkGrammar.json` too: `test_shared_constants.py` fails until
the file lists the schema's families, and Jest until `FAMILY_KIND` in
`utils/autkSpecKind.ts` routes each one.

## Organizing Contributions

To maintain the codebase, contributors are encouraged to submit detailed issues or focused pull requests. The following guidelines and templates can help you structure contributions clearly and effectively.

### Defining the Scope of a Pull Request

When creating a PR, it's important to have a clear, focused scope. Each PR should ideally address a single feature or issue. Avoid mixing unrelated changes as it makes the review process harder and less transparent. If you need to address multiple unrelated changes, create separate branches and PRs for each.

**Focus on:**

* One feature addition
* One bug fix
* One set of related documentation updates

If your PR grows beyond a single scope, consider splitting it into multiple PRs.

### Pull Request Template

To help maintain consistency and clarity, use the following template when creating a Pull Request:

```md
### Description
<!-- A brief description of what your PR does. Include the purpose and context. -->

### Related Issue
<!-- If this PR addresses an issue, provide the issue number or link. -->

### Changes
<!-- List the changes or additions you've made. For example:
- Added a new API endpoint to retrieve user profiles.
- Fixed a typo in the README.
-->

### Impact
<!-- Describe who will be affected by these changes and how. For instance:
- Users now have the ability to do X.
- Bug Y is no longer encountered.
-->

### Testing
<!-- Detail any steps or tests taken to ensure the code works as intended.
Include steps for reviewers to reproduce and verify your changes:
1. Run `npm install`
2. Run `npm test`
3. Confirm that all tests pass and the new feature works as expected.
-->

### Additional Notes
<!-- Any additional context, concerns, or follow-ups. For example, mention if docs need to be updated after merging. -->
```

### Issue Template

Issues are the best way to report bugs, request new features, or start a discussion around potential changes. Before creating a new issue, make sure to:

* Check if the issue already exists.
* Provide as much relevant detail as possible.

Use the following template when creating a new issue:

```md
### Summary
<!-- Provide a concise description of the issue. -->

### Steps to Reproduce
<!-- List the steps to replicate the problem -->

### Expected Result
<!-- What did you expect to happen? -->

### Actual Result
<!-- What actually happened? -->

### Environment
<!-- OS, Browser, Node version, Branch, etc. -->

### Additional Information
<!-- Screenshots, logs, temporary workarounds, etc. -->
```

## Advice for Students

* Start small - improving documentation or examples is a valuable first step.
* Ask questions early, especially if you're unfamiliar with the stack.
* Use GitHub Issues to propose ideas and get feedback.
* Consider pairing contributions with coursework or independent study.
* If you're committing to a larger contribution, reach out for mentorship.

## Need Help

* Post in the GitHub Discussions or Issues tab

## Final Notes

Every contribution helps. You don’t need deep expertise, just curiosity, commitment, and a willingness to learn.
