# Contributing to Curio

This guide is intended for students who are interested in contributing to an open-source software project, as well as for developers looking to participate in the Curio ecosystem. It provides a structured and detailed overview of the system, its architecture, and various ways to contribute. Whether you're building your first pull request or integrating advanced features, this document is designed to support your contribution journey.

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
  * [Frontend Unit Tests](#frontend-unit-tests)
  * [Frontend E2E Tests](#frontend-e2e-tests)
  * [Database Migrations](#database-migrations)
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
| Frontend  | JavaScript, Autark, Vega-Lite          | Browser-based interface for authoring and interacting with dataflows |
| Execution | Python sandbox (multiprocess)          | Secure module for executing user code                                |
| DevOps    | Docker, Docker Compose, GitHub Actions | Containerization, deployment, and CI/CD                              |
| Packaging | PyPI (`utk-curio`)                     | Distributes the CLI and backend/frontend bundle                      |

## Repository Structure

The codebase follows a modular structure under the `utk_curio/` directory. This separation supports clean boundaries between backend, frontend, and execution logic.

```
curio/
├── utk_curio/
│   ├── backend/                     # Manages database access and user authentication
│   │   └── tests/                   # pytest files for backend
│   ├── sandbox/                     # Executes user Python code in a secure environment
│   │   └── tests/                   # pytest files for sandbox
│   └── frontend/                    # All frontend logic
│       └── urban-workflows/         # Main Curio interface for dataflow editing
│           └── src/
│               └── components/     # React components and CSS
│
├── curio.py                        # CLI entry point for running and managing all services
├── tests/                          # Dataflow examples for testing
├── docs/                           # Documentation, usage guides, and examples
└── requirements.txt                # Backend and sandbox dependencies
```

For a step-by-step walkthrough of adding a new node type, including a worked example (`DATA_SUMMARY`), see [ADDING-NODES.md](ADDING-NODES.md). For a deep dive into how the system is structured (nodes, data flow, execution pipeline, provenance) see [ARCHITECTURE.md](ARCHITECTURE.md).

## Installation Options

### Via pip (lightweight setup)

```bash
pip install utk-curio
curio start
```

This installs the CLI and a pre-built version of the frontend. You won’t be able to modify or rebuild the UI from this setup.

### From GitHub (for development)

```bash
git clone https://github.com/urban-toolkit/curio.git
cd curio
python curio.py start
```

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

### Documentation

* Write developer setup instructions or onboarding checklists
* Add usage diagrams, screenshots, or schema explanations
* Contribute inline documentation and docstrings

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
   python curio.py start
   ```

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

A single script starts all Curio services, runs unit tests and Playwright E2E tests, then shuts everything down:

```bash
./scripts/test.sh
```

Common shortcuts:

```bash
# containers already running, unit tests only
./scripts/test.sh --use-existing --unit-only

# watch the browser, specific workflows only
./scripts/test.sh --use-existing --e2e-only --headed --workflows Vega.json,Regression.json
```

See `./scripts/test.sh --help` for all options, or read the sections below for more detail.

### One-Time Setup

Install the Playwright browser once (use the same Python/venv you use for pytest):

```bash
playwright install chromium
# or: python -m playwright install chromium
```

### Backend and Sandbox Tests

```bash
pytest utk_curio/backend/tests/
pytest utk_curio/sandbox/tests/
```

### Frontend Unit Tests

The frontend uses Jest and React Testing Library for component and TypeScript unit tests.

```bash
cd utk_curio/frontend/urban-workflows
npm test -- --watchAll=false
```

Tests live under `src/tests/` and mirror the structure of `src/components/`. See [utk_curio/frontend/urban-workflows/src/tests/README.md](../utk_curio/frontend/urban-workflows/src/tests/README.md) for guidelines on writing and organizing tests.

### Frontend E2E Tests

The frontend tests use Playwright to upload workflow JSON files into the Curio UI and verify the ReactFlow canvas renders correctly.

```bash
# full suite
pytest utk_curio/backend/tests/test_frontend/

# watch the browser while tests run
pytest utk_curio/backend/tests/test_frontend/ --headed

# use already-running servers (e.g. docker compose)
CURIO_E2E_USE_EXISTING=1 pytest utk_curio/backend/tests/test_frontend/
```

Run only specific workflows by setting `CURIO_E2E_WORKFLOWS` (comma-separated basenames):

```bash
CURIO_E2E_WORKFLOWS=Vega.json,Regression.json pytest utk_curio/backend/tests/test_frontend/test_workflows.py
```

Preview which tests will run without executing them:

```bash
pytest --collect-only utk_curio/backend/tests/test_frontend/test_workflows.py
```

Run a single workflow test:

```bash
# one workflow, one test method
pytest utk_curio/backend/tests/test_frontend/test_workflows.py::TestWorkflowCanvas::test_node_and_edge_count[Vega.json]

# all checks for one workflow
pytest utk_curio/backend/tests/test_frontend/test_workflows.py -k "Vega.json"
```

**Test matrix** — each workflow runs four checks:

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

* Join the [Curio Discord server](https://discord.gg/vjpSMSJR8r)
* Post in the GitHub Discussions or Issues tab

## Final Notes

Every contribution helps. You don’t need deep expertise—just curiosity, commitment, and a willingness to learn.
