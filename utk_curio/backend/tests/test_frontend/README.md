# Frontend E2E Tests

See [CONTRIBUTING.md](../../../../docs/CONTRIBUTING.md#frontend-e2e-tests)
for the repo-wide E2E workflow. Test-specific details live here.

Playwright-based end-to-end tests that upload workflow JSON files into the Curio frontend and verify the ReactFlow canvas renders correctly.

## Run

```bash
# full suite (CURIO_TESTING=1 is exported by test.sh; set it explicitly if you invoke pytest directly)
CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/

# headed (watch the browser)
CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/ --headed

# use already-running servers (e.g. docker compose); the caller is responsible for
# booting them with CURIO_TESTING=1 + DATABASE_URL pointing at the test DB
CURIO_E2E_USE_EXISTING=1 pytest utk_curio/backend/tests/test_frontend/
```

## Test database contract

These tests boot the **real** backend through `curio.py start`, so they must never touch the developer's dev DB. The strategy keeps dev and test state fully separate:

- `CURIO_TESTING=1` switches `utk_curio/backend/config.py` to a test-only SQLAlchemy URL under `<CURIO_LAUNCH_CWD>/.curio/test/urban_workflow_test.db` (never the dev `urban_workflow.db`).
- A session-scoped `test_databases` fixture in `utk_curio/backend/tests/conftest.py` runs **once before any E2E test or the `curio start` subprocess**:
  1. creates a clean workspace directory (temp by default, or `CURIO_TEST_WORKSPACE` if set),
  2. sets `CURIO_LAUNCH_CWD`, `DATABASE_URL` (→ `sqlite:///…/urban_workflow_test.db`), and `CURIO_TESTING=1` in `os.environ` so the subprocess inherits them,
  3. **wipes** any pre-existing `urban_workflow_test.db` and re-creates the schema via `flask db upgrade`.
- A function-scoped autouse `e2e_clean_db` fixture truncates the mutable tables (`user`, `user_session`, `auth_attempt`, `project`, `exec_cache_entry`) between tests so hardcoded usernames like `e2etestuser`, `ownera`, `ownerb`, `prjtester` can be re-created fresh in every test.

In other words: **every pytest invocation starts against an empty database**, and tests are independent of each other — the same isolation Django's test runner aims to provide.

| Variable | Purpose |
|---|---|
| `CURIO_TESTING` | When `1`, backend uses test-only DB paths (set automatically by `test.sh`). |
| `DATABASE_URL_TEST` | Override for the SQLAlchemy test DB URL (defaults to `sqlite:///…/.curio/test/urban_workflow_test.db`). |
| `CURIO_TEST_WORKSPACE` | Persist the temp workspace at this path instead of `tempfile.mkdtemp` (useful for debugging). |

## Authenticated test setup

The SPA wraps `/projects` and `/workflow/:id?` in `RequireAuth`, so every E2E test needs an authenticated browser session before it can interact with those pages. Two reusable strategies live in [`utils.py`](utils.py); pick based on what the test is actually asserting.

### Strategy A — drive the signup form (UI coverage)

Use when the test's purpose is to exercise the real `/auth/signup` / `/auth/signin` pages, or when a test must hit the exact same code path a first-time user would. Helpers:

| Helper | What it does |
|---|---|
| `signup_e2e_user(page, base_url, *, name, username, password=DEFAULT_TEST_PASSWORD)` | Fills `/auth/signup`, submits, waits for redirect to `/projects`. |
| `open_new_workflow(page)` | From `/projects`, clicks `+ New Workflow` and waits for `/workflow/**`. |
| `signup_and_enter_new_workflow(page, base_url, *, name, username, password=…)` | Convenience wrapper: signup + `+ New Workflow`. |

Used by `test_auth_flow.py`, `test_project_save_load.py`, `test_project_dirty_guard.py`, `test_project_ownership.py`.

### Strategy B — DB stub (fast path)

Use when auth is incidental setup rather than the subject of the test (e.g. `test_workflows.py`'s parametrized canvas checks, one signup per workflow class ≈ seconds saved). The browser session is prepared through test-only backend endpoints instead of the signup UI:

1. `POST /api/testing/stub-login` → create-or-find a user, store the password hash, return `{user, token, created}`.
2. `POST /api/testing/stub-project` → seed an empty `Project` owned by that user and return `{id, name, slug, …}`.

The blueprint lives in [`utk_curio/backend/app/testing/routes.py`](../../app/testing/routes.py) and is **only registered by `create_app` when `CURIO_TESTING=1`**; each handler also re-guards at request time with `abort(404)`. Helpers:

| Helper | What it does |
|---|---|
| `stub_db_login(page, frontend_url, backend_url, *, username, name, password=…, project_name=None, project_spec=None)` | POSTs to `/api/testing/stub-login`, installs the returned token as the `session_token` cookie on `page.context`, and optionally seeds a project via `/api/testing/stub-project`. |
| `install_session_cookie(page, frontend_url, token)` | Low-level: matches `js-cookie`'s defaults (path=`/`, host-only) so the SPA's `Cookies.get("session_token")` finds the same value. |
| `stub_login_and_enter_workflow(page, frontend_url, backend_url, *, username, name, password=…, project_name="StubbedWorkflow", project_spec=None)` | Stubs user + empty project, installs the cookie, and navigates **directly** to `/workflow/<project_id>` — no `/auth/signup`, no `+ New Workflow` click. Used by the class-scoped `loaded_workflow` fixture. |

The DB stub is strictly additive — Strategy A still works against the same test DB. Keep project-ownership / signup UI tests on Strategy A so regressions in the real auth flow still fail those tests.

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
| `test_node_execution` | Nodes execute correctly and produce the expected output |

## File Layout

```
test_frontend/
  conftest.py                 # workflow list, env filtering, pytest_generate_tests hook
  fixtures.py                 # server startup, browser/page fixtures, loaded_workflow (DB-stub login)
  utils.py                    # FrontendPage, upload_workflow, signup helpers, stub_* helpers
  test_alive.py               # smoke tests: backend, sandbox, frontend are live
  test_auth_flow.py           # signup → projects → signout → signin (UI path)
  test_workflows.py           # TestWorkflowCanvas — DB-stubbed auth via loaded_workflow
  test_project_save_load.py   # + New Workflow → save → reload (UI auth)
  test_project_dirty_guard.py # beforeunload guard on dirty canvas (UI auth)
  test_project_ownership.py   # two-user isolation via /api/projects (UI auth)
  test_guest_project_cleanup.py
  test_guest_flag.py          # ALLOW_GUEST_LOGIN toggle
  test_no_project_menu.py     # File-menu UI in --no-project mode (CURIO_NO_PROJECT=1)
```

## CURIO_NO_PROJECT-mode tests

The suite has two configurations with mutually-exclusive UI surfaces:

- **default** (`CURIO_NO_PROJECT=0`, the implicit value): the SPA exposes a per-user `/projects` page and the File menu offers `New dataflow` / `Load dataflow` / `Save dataflow` / `Save dataflow as` / `Export as notebook` / `Go to projects`.
- **no-project** (`CURIO_NO_PROJECT=1`): the SPA auto-guest-signs in, routes `/` directly to `/dataflow`, and hides only the project-backed entries (`Save dataflow` and `Go to projects`); `New dataflow`, `Load dataflow`, `Save dataflow as`, and `Export as notebook` remain visible.

Tests that depend on either surface call `require_project_page()` / `require_no_project_mode()` from [`utils.py`](utils.py) (both consult the live backend's `/api/config/public` so the pytest process and the `curio start` subprocess never disagree). To exercise the no-project UI explicitly:

```bash
CURIO_NO_PROJECT=1 CURIO_TESTING=1 pytest \
    utk_curio/backend/tests/test_frontend/test_no_project_menu.py \
    utk_curio/backend/tests/test_frontend/test_alive.py
```

`fixtures.py::curio_servers` reads `CURIO_NO_PROJECT` from the pytest env and forwards `--no-project` to `curio.py start`, so no extra wiring is needed.

## Environment Variables

| Variable | Purpose |
|---|---|
| `CURIO_E2E_WORKFLOWS` | Comma-separated workflow basenames to run (default: all) |
| `CURIO_E2E_USE_EXISTING` | Set to `1` to skip server startup and use running servers (must already be booted with `CURIO_TESTING=1`) |
| `CURIO_E2E_HOST` | Host for existing servers (default: `localhost`) |
| `CURIO_E2E_BACKEND_PORT` | Backend port for existing servers (default: `5002`) |
| `CURIO_E2E_SANDBOX_PORT` | Sandbox port for existing servers (default: `2000`) |
| `CURIO_E2E_FRONTEND_PORT` | Frontend port for existing servers (default: `8080`) |
| `CURIO_TESTING` | Switches backend to test-only DB paths under `.curio/test/`. Required for any test that boots the real backend. |
| `DATABASE_URL_TEST` | SQLAlchemy URL for the test DB (defaults to `sqlite:///…/.curio/test/urban_workflow_test.db`). |
| `CURIO_TEST_WORKSPACE` | Persist the per-session test workspace here instead of a temp dir (debugging). |
