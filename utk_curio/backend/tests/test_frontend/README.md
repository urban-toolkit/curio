# Frontend E2E Tests

Playwright-based end-to-end tests that upload workflow JSON files into the Curio frontend and verify the ReactFlow canvas renders correctly.

## Run

```bash
# full suite
pytest utk_curio/backend/tests/test_frontend/

# headed (watch the browser)
pytest utk_curio/backend/tests/test_frontend/ --headed

# use already-running servers (e.g. docker compose)
CURIO_E2E_USE_EXISTING=1 pytest utk_curio/backend/tests/test_frontend/
```

## Workflow Subset Filtering

Run only specific workflows by setting `CURIO_E2E_WORKFLOWS` (comma-separated basenames):

```bash
CURIO_E2E_WORKFLOWS=Vega.json,UTK.json pytest utk_curio/backend/tests/test_frontend/test_workflows.py
```

When unset, all workflows listed in `conftest.py::WORKFLOW_FILES` are tested.

## Dry Run

Preview which tests will run without executing them:

```bash
pytest --collect-only utk_curio/backend/tests/test_frontend/test_workflows.py
```

## Run a Single Test

```bash
# one workflow, one test method
pytest utk_curio/backend/tests/test_frontend/test_workflows.py::TestWorkflowCanvas::test_node_and_edge_count[Vega.json]

# all checks for one workflow
pytest utk_curio/backend/tests/test_frontend/test_workflows.py -k "Vega.json"
```

## Test Matrix

`TestWorkflowCanvas` is parametrized per workflow via `pytest_generate_tests` in `conftest.py`. Each workflow runs three checks:

| Test | What it verifies |
|---|---|
| `test_node_and_edge_count` | Canvas has the exact node/edge counts from the JSON |
| `test_node_positions` | Relative x-ordering of nodes is preserved |
| `test_node_type_and_content` | Correct editor widget per node category (code, grammar, datapool, passive) |

## File Layout

```
test_frontend/
  conftest.py        # workflow list, env filtering, pytest_generate_tests hook
  fixtures.py        # server startup, browser/page fixtures, loaded_workflow
  utils.py           # helpers (FrontendPage, upload_workflow, port utils)
  test_alive.py      # smoke tests: backend, sandbox, frontend are live
  test_workflows.py  # TestWorkflowCanvas + workflow JSON parser
```

## Environment Variables

| Variable | Purpose |
|---|---|
| `CURIO_E2E_WORKFLOWS` | Comma-separated workflow basenames to run (default: all) |
| `CURIO_E2E_USE_EXISTING` | Set to `1` to skip server startup and use running servers |
| `CURIO_E2E_HOST` | Host for existing servers (default: `localhost`) |
| `CURIO_E2E_BACKEND_PORT` | Backend port for existing servers (default: `5002`) |
| `CURIO_E2E_SANDBOX_PORT` | Sandbox port for existing servers (default: `2000`) |
| `CURIO_E2E_FRONTEND_PORT` | Frontend port for existing servers (default: `8080`) |
