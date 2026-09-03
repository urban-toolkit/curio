# Frontend E2E Tests

See [CONTRIBUTING.md](../../../../docs/CONTRIBUTING.md#frontend-e2e-tests)
for the repo-wide E2E workflow. Test-specific details live here.

Playwright-based end-to-end tests that upload workflow JSON files into the Curio frontend and verify the ReactFlow canvas renders correctly.

## Run

```bash
# full suite
pytest utk_curio/backend/tests/test_frontend/

# headed (watch the browser; required for AUTK fixtures to actually render, see below)
pytest utk_curio/backend/tests/test_frontend/ --headed

# use already-running servers (e.g. docker compose); the caller is responsible for
# booting them with CURIO_TESTING=1 + DATABASE_URL pointing at the test DB
CURIO_E2E_USE_EXISTING=1 pytest utk_curio/backend/tests/test_frontend/
```

### Parallel

```bash
python curio.py test e2e --parallel 4          # boots the stack + 3 extra pairs, runs 4 xdist workers
bash scripts/test.sh --e2e-only --parallel auto # auto = min(4, cores/4)
```

Every worker gets its **own backend+sandbox pair** behind the one frontend. That
is the unit of isolation, not the test: the suite truncates `user` / `project` /
`user_session` between tests through `/api/testing/reset-db`, so two workers on
one backend would delete each other's logged-in users mid-test. Shard 0 is the
stack as configured; shards 1..N-1 get their ports, sqlite DB, DuckDB store,
dataset-catalog copy and logs from `backend/tests/shards.py`, relocated under
`.curio/shards/<k>/` through `CURIO_STATE_DIR`. The bundle picks its backend at
runtime (`window.__CURIO_BACKEND_URL__`, injected per browser context by the
`browser` fixture), so one webpack build serves all of them.

Tests are scheduled with `--dist loadgroup`: one group per workflow in
`test_workflows.py` (its four class-scoped methods share a browser and a login),
one group per file everywhere else. A missing screenshot baseline **fails**
under xdist instead of being minted -- see *Screenshot baselines*.

With `--use-existing`, pairs 1..N-1 must already be running on the ports
`python -m utk_curio.backend.tests.shards K` prints (that is what CI does,
inside its one container).

### AUTK / WebGPU note

Autark workflows use the single `AUTK_GRAMMAR` node type, which renders its map/plot via WebGPU. The `browser_type_launch_args` fixture in the **parent** [`../conftest.py`](../conftest.py) points `executable_path` at the system-installed Google Chrome and passes a minimal flag set (`--enable-unsafe-webgpu --enable-unsafe-swiftshader`). This is deliberate: Playwright's bundled Chromium on Windows ships without a working Dawn/WebGPU runtime (`requestAdapter()` returns null), whereas real Chrome 113+ returns an adapter. When Chrome can't be found it falls back to bundled Chromium.

There is **no WebGPU tolerance**: an `AUTK_GRAMMAR` node that errors (including because WebGPU is unavailable) is a hard test failure. To run the autk examples you need a browser that provides WebGPU - which the system-Chrome `executable_path` above ensures. `_webgpu_diagnostics` still probes adapter/device state once per session and attaches it to the failure dump for debugging.

`AUTK_GRAMMAR` is a `"grammar"` node (grammar/JSON editor + output tab) and exercises the full matrix: `test_node_type_and_content` checks the grammar editor; `test_node_execution` verifies each node reaches **Done**. Its grammar content (and any JavaScript/WGSL compute blocks) is excluded from the Python random-seed injection used by Python `CODE_TYPES` nodes.

## Test database contract

These tests boot the **real** backend through `curio.py start`, so they must never touch the developer's dev DB. The strategy keeps dev and test state fully separate:

- `CURIO_TESTING=1` switches `utk_curio/backend/config.py` to a test-only SQLAlchemy URL under `<CURIO_LAUNCH_CWD>/.curio/test/urban_workflow_test.db` (never the dev `urban_workflow.db`).
- A session-scoped `test_databases` fixture in `utk_curio/backend/tests/conftest.py` runs **once before any E2E test or the `curio start` subprocess**:
  1. creates a clean workspace directory (temp by default, or `CURIO_TEST_WORKSPACE` if set),
  2. sets `CURIO_LAUNCH_CWD`, `DATABASE_URL` (→ `sqlite:///…/urban_workflow_test.db`), and `CURIO_TESTING=1` in `os.environ` so the subprocess inherits them,
  3. **wipes** any pre-existing `urban_workflow_test.db` and re-creates the schema via `flask db upgrade`.
- A function-scoped autouse `e2e_clean_db` fixture truncates the mutable tables (`user`, `user_session`, `auth_attempt`, `project`, `exec_cache_entry`) between tests so hardcoded usernames like `e2etestuser`, `ownera`, `ownerb`, `prjtester` can be re-created fresh in every test.

In other words: **every pytest invocation starts against an empty database**, and tests are independent of each other - the same isolation Django's test runner aims to provide.

| Variable | Purpose |
|---|---|
| `CURIO_TESTING` | When `1`, backend uses test-only DB paths **and** mounts the `/api/testing/*` stubs. Exported by [`../conftest.py`](../conftest.py) at import time, so every pytest run under `tests/` already has it; a server started outside pytest needs it passed in. |
| `DATABASE_URL_TEST` | Override for the SQLAlchemy test DB URL (defaults to `sqlite:///…/.curio/test/urban_workflow_test.db`). |
| `CURIO_TEST_WORKSPACE` | Persist the temp workspace at this path instead of `tempfile.mkdtemp` (useful for debugging). |

## Authenticated test setup

The SPA wraps `/projects` and `/workflow/:id?` in `RequireAuth`, so every E2E test needs an authenticated browser session before it can interact with those pages. Two reusable strategies live in [`utils.py`](utils.py); pick based on what the test is actually asserting.

### Strategy A - drive the signup form (UI coverage)

Use when the test's purpose is to exercise the real `/auth/signup` / `/auth/signin` pages, or when a test must hit the exact same code path a first-time user would. Helpers:

| Helper | What it does |
|---|---|
| `signup_e2e_user(page, base_url, *, name, username, password=DEFAULT_TEST_PASSWORD)` | Fills `/auth/signup`, submits, waits for redirect to `/projects`. |
| `open_new_workflow(page)` | From `/projects`, clicks `+ New Workflow` and waits for `/workflow/**`. |
| `signup_and_enter_new_workflow(page, base_url, *, name, username, password=…)` | Convenience wrapper: signup + `+ New Workflow`. |

Used by `test_auth_flow.py`, `test_project_save_load.py`, `test_project_dirty_guard.py`, `test_project_ownership.py`.

### Strategy B - DB stub (fast path)

Use when auth is incidental setup rather than the subject of the test (e.g. `test_workflows.py`'s parametrized canvas checks, one signup per workflow class ≈ seconds saved). The browser session is prepared through test-only backend endpoints instead of the signup UI:

1. `POST /api/testing/stub-login` → create-or-find a user, return `{user, token, created}`. The password is stored only when the account is created; an existing account keeps the hash it had.
2. `POST /api/testing/stub-project` → seed an empty `Project` owned by that user and return `{id, name, slug, …}`.

The blueprint lives in [`utk_curio/backend/app/testing/routes.py`](../../app/testing/routes.py). `create_app` registers it whenever `_is_dev()` (`CURIO_ENV != 'prod'`), and a blueprint-level `before_request` then refuses with 404 unless **both** `_is_dev()` and `CURIO_TESTING` hold. `CURIO_ENV` defaults to `dev`, so the second factor is what keeps `stub-login` off an ordinary deployment. Helpers:

| Helper | What it does |
|---|---|
| `stub_db_login(page, frontend_url, backend_url, *, username, name, password=…, project_name=None, project_spec=None)` | POSTs to `/api/testing/stub-login`, installs the returned token as the `session_token` cookie on `page.context`, and optionally seeds a project via `/api/testing/stub-project`. |
| `install_session_cookie(page, frontend_url, token)` | Low-level: matches `js-cookie`'s defaults (path=`/`, host-only) so the SPA's `Cookies.get("session_token")` finds the same value. |
| `stub_login_and_enter_workflow(page, frontend_url, backend_url, *, username, name, password=…, project_name="StubbedWorkflow", project_spec=None)` | Stubs user + empty project, installs the cookie, and navigates **directly** to `/workflow/<project_id>` - no `/auth/signup`, no `+ New Workflow` click. Used by the class-scoped `loaded_workflow` fixture. |

The DB stub is strictly additive - Strategy A still works against the same test DB. Keep project-ownership / signup UI tests on Strategy A so regressions in the real auth flow still fail those tests.

**One footgun in the stub spec.** `_empty_spec()` sets a top-level `name` but no
`dataflow.name`, so `loadParsedTrill` calls `setWorkflowName(undefined)` and the
canvas ends up with no workflow name at all (it clobbers `FlowProvider`'s
`"DefaultDataflow"` default). Nothing notices until a test presses **File > New
dataflow** and then **Save**: `discardProject()` clears `projectName`, so
`saveCurrentProject` sends `nameOverride || projectName || workflowNameRef.current`
= `undefined`, and `ProjectCreate` rejects it with `name is required`. The symptom
is an error toast and a URL that stays on `/dataflow/new`, because `handleSave`
only navigates after a successful create. A test that needs a second empty
dataflow should stub another project rather than create one through the File
menu.

### Shared helpers

| Helper | What it does |
|---|---|
| `api_json(url, token, *, method="GET", payload=None, timeout=10.0, raw=False)` | Authenticated JSON request, stdlib only. The escape hatch for asserting backend state from a browser test: a seeding or persistence problem then fails in about a second with the offending payload, instead of as a 15-second locator timeout that says nothing about which side broke. `raw=True` returns bytes, for binary endpoints such as a `.curio.zip`. |
| `require_owner_view(page, *, timeout=4000)` | **Fails** when the dataflow opened read-only as the shared guest. A guest cannot see another user's installed packages, datasets or agents, so every catalog fetch comes back empty and the test asserts nothing. This used to skip, which hid the problem: `scripts/test.sh` booted its shared stack without `--auth` and 43 tests across 22 files quietly skipped while the run reported green. The environment being wrong is a setup bug, so it is loud. Boot with `--auth`. |
| `open_tools_palette(page, kind)` | Opens the left-rail `"packages"` or `"datasets"` palette and returns its panel locator. Re-callable: it matches either the `Open …` or the `Close …` title and clicks only when the panel is not already showing, so a test that needs both palettes can come back to the first one. They are still mutually exclusive (`ToolsMenu` keeps a single `activePalette`), so opening one closes the other. |

### Canvas authoring helpers

Everything else in this suite gets its graph from a file or a seeded spec. These
build one by hand, the way a user does, and they are the only coverage of the
palette drag and the edge drag.

| Helper | What it does |
|---|---|
| `drag_to_canvas(page, source, *, at=None)` | One synthetic HTML5 drag from any draggable palette source onto `.curio-canvas-drop-target`; returns the new node's id, diffed from the canvas because ids are `uuid4`. |
| `connect_nodes(page, source_id, target_id, *, source_handle="out", target_handle="in")` | Draws an edge with real pointer moves between two `.react-flow__handle`s and returns the derived edge id. |
| `set_node_code(page, node_id, code)` / `read_node_code(page, node_id)` | Writes / reads a code node's source through that node's own Monaco instance. |
| `canvas_nodes(page)` / `canvas_node_type(page, node_id)` | `{id, nodeType}` for the canvas, read from `window.__curio_reactFlow`. Projected, because `node.data` holds a `PythonInterpreter` and callbacks that Playwright cannot serialize. |
| `play_node`, `wait_for_node_done`, `wait_for_node_settled`, `run_node_and_wait` | Press a node's play button and wait for it to settle. `wait_for_node_done` raises with the node's own error text; `wait_for_node_settled` returns `"done"` / `"error"` for a test where the failure *is* the expected outcome. |
| `read_node_output_text(page, node_id)` | The inline output box's text: the `[N]:` counter, stdout, and `Saved to file: …`. The return value is never shown, so a result assertion has to `print` what it wants to check. |
| `activate_header_icon(locator)` | Presses a node-header icon button (the title pencil, the settings gear). |
| `dismiss_toasts(page)` | Closes visible toasts and waits for the toast region to stay quiet, so a late toast cannot drift into a screenshot. Safe when there are none. **Never call it before an assertion about a toast** - `test_computed_json_output_e2e.py` records toasts through a MutationObserver instead, because `showToast` removes each one after 5 s. |

Five things here are easy to get wrong:

- **The identifying attribute is often not the draggable element.** A dataset
  palette row carries `data-dataset-id` on its wrapper and puts `onDragStart` on
  an inner grip, so `drag_to_canvas` resolves a `[draggable]` descendant - events
  bubble up, never down.
- **`dragstart` must be fired on the source.** Dataset drags keep their payload in
  a module singleton set by `beginDatasetDrag`, which the canvas reads in
  preference to `getData`, so a hand-built `drop` on its own carries nothing and
  `handleDrop` ignores it without a word.
- **Nodes are 525x350 at zoom 1.** In a 1280x720 viewport, drops less than ~600 px
  apart horizontally overlap, and the later node's body then covers the earlier
  one's handle. React Flow hit-tests whatever is under the pointer, so the
  connection drag becomes a silent no-op; `connect_nodes` checks
  `elementFromPoint` up front and fails with the covering element instead.
- **Never `keyboard.type` into Monaco.** `autoClosingBrackets: "always"` and
  `formatOnType: true` mean typed Python does not round-trip. `setValue` fires the
  same `onChange` -> `floatCode` -> `data.code` chain a keystroke does, so it is
  the user path, not a back door.
- **Never `__curio_reactFlow.setNodes`.** That writes only React Flow's zustand
  store, and `useStoreUpdater` pushes the provider's node array straight back over
  it on the next render, so an injected node or code edit silently disappears.

Node-header icons need `activate_header_icon` rather than `click()`: they activate
on `pointerdown` + `pointerup` and swallow the native click (so press-and-drag
still moves the node), and app chrome overlaps the header band at the top of the
canvas, which means a real click at the button's centre lands on the overlay.

### Browser-test conventions

Three things are easy to get wrong against the catalog drawers:

- **Disable motion before navigating.** `page.emulate_media(reduced_motion="reduce")` - both drawer providers read `prefers-reduced-motion` through `useSyncExternalStore`, so this makes presentation synchronous and collapses the 380 ms close timer to zero. Do it *before* `stub_login_and_enter_workflow`; a `page.reload()` afterwards races `ProjectLoader` into the shared-guest fallback.
- **`to_be_visible()` is not a gate for a drawer.** All three slide in via `transform: translate3d(100%, 0, 0)`, which keeps a full bounding box off-screen. **`aria-hidden="false"` is not a gate either, despite what this file used to say.** It is the presented signal for the Dataset and Agent drawers, but the Node Catalog drawer carried no `aria-hidden` at all until the fix that added it, so waiting for the attribute to flip there waited forever - a whole chapter of the stress run died on that advice. Gate on where the panel actually *is*: `stress.py::wait_for_drawer_presented` polls the dialog's bounding box until its left edge is inside the viewport, which is true of all three regardless of what they advertise. `canvasDrawerParity.test.ts` now keeps the three from diverging again. Never `force=True` on drawer internals - `force` skips the very hit-target check that protects against clicking a mid-slide panel.
- **Settle the canvas before clicking anything on a node.** ReactFlow's initial `fitView` animates the viewport, and a visible-but-still-moving element makes `click()` time out with no useful message. Call `_wait_for_reactflow_ready(page)` first.

## Screenshot baselines

`save_workflow_test_screenshot` compares the canvas against a PNG in
`docs/examples/dataflows/expected_outputs/`, named
`screenshot_<stem>_<test_name>.png`. **A missing baseline is not a failure** - the
helper writes the current capture as the new baseline and passes, so the first run
of a new test silently establishes whatever it happened to render. Review a new
baseline by eye before trusting it.

The helper calls `_wait_for_reactflow_ready` first, so baseline and comparison
always share one fitView'd viewport. Comparison allows 20% of pixels to differ by
more than 30/255 per channel; that budget exists because every executed code node
renders `Saved to file: <timestamp>_<hash>`, which changes on every run.

Pass `fit_reactflow=False` for a page that has no canvas - the projects list, the
catalog. That fitView step waits on `.react-flow__node`, so it would otherwise
burn its whole timeout waiting for a node that is never going to appear. Note
that `_capture_full_page` measures the *document*, so a page whose scrolling
lives in an inner `overflow-y: auto` container needs two captures, at the top and
at the bottom, to show anything moved; `test_project_page_scroll_e2e.py` does
exactly that.

Call `dismiss_toasts(page)` before capturing anything that follows a node run.
Toasts are bottom-right, up to 360px wide, and land exactly where canvas content
usually is - and a node reaching "Done" does not mean its follow-up work has
finished: the dataset install-save is debounced 500 ms past it and answers
seconds later, so any toast it raises lands well after the status flips. A single
sweep dismisses nothing and the toast still makes the capture; the helper sweeps,
waits for a quiet window, and sweeps again.

A *"couldn't be generated"* warning is a **bug**, not routine noise (#180):
`test_computed_json_output_e2e.py` fails on it. Sweeping is for the ordinary
toasts (saves, installs), not for hiding that one.

Two families of baseline live in that folder:

- one per bundled dataflow JSON, for `TestWorkflowCanvas` (two per workflow,
  `test_node_type_and_content` and `test_node_execution`), each paired with a
  `_browser_log.txt` because autk swallows its errors into React state;
- one per hand-built surface, keyed by the stem the test passes in place of a
  workflow path: `canvas-authoring`, `package-roundtrip`,
  `package-metadata-roundtrip`, `package-export-drawer`, `save-as-modal`,
  `library-manager`, `node-catalog-drawer`, `data-catalog-drawer`,
  `agent-catalog-drawer`, `agent-run` (one per built-in agent, plus a
  `_chat` companion for the four that mutate), `agent-review-card`,
  `dataset-export`, `dataset-lineage`, `autark-grammar-edit`,
  `merge-flow-authoring`, `canvas-delete-key`, `projects-page-scroll`,
  `global-imports`, `uhvi-install`, `data-pool-scroll`,
  `computed-json-output` and `workflow-deps-import`. These guard what the semantic assertions cannot see -
  most usefully that an edge is actually *drawn*, not merely present in the
  React Flow store, and that a modal rendered the values the test typed in.

One test may capture more than once by varying `test_name`, and a *file* may
capture under one stem from several tests.
`test_package_metadata_roundtrip_e2e.py` takes three under the
`package-metadata-roundtrip` stem, because its subject is a sequence of modals
and a single end-state shot would show none of them. Capture while the modal is
still open: `_capture_full_page` uses `full_page=True` and `ModalShell` portals
into `document.body`, so an open modal is in the shot.

Non-determinism inside a capture is normal and the 20% budget is what absorbs it.
The metadata modal, for instance, renders the generated coordinate
(`curio.canvas.draft.<random>@1`) in its subtitle, which differs on every run. Do
not tighten the tolerance to chase a crisper diff.

Measured run-to-run drift for the three full-canvas baselines
(`canvas-authoring`, `package-roundtrip`, `library-manager`) is 1.24% (library
manager) and under 0.1% (the other two) against the 20% budget, so the headroom is
wide. They were captured with the executable `browser_type_launch_args` resolves
to - **system Google Chrome** when it is installed, bundled Chromium otherwise -
so regenerate them on the machine that will police them if that ever diverges. To
regenerate, delete the PNG and re-run the test.

A failing comparison writes `screenshot_<stem>_<test_name>_actual.png` next to the
baseline and attaches expected/actual/diff to the Allure report. Those `_actual`
files are debris; do not commit them.

## Workflow Subset Filtering

Run only specific workflows by setting `CURIO_E2E_WORKFLOWS` (comma-separated basenames):

```bash
CURIO_E2E_WORKFLOWS=Vega.json,AutkMap.json pytest utk_curio/backend/tests/test_frontend/test_workflows.py
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
  test_workflows.py           # TestWorkflowCanvas - DB-stubbed auth via loaded_workflow
  test_project_save_load.py   # + New Workflow → save → reload (UI auth)
  test_project_dirty_guard.py # beforeunload guard on dirty canvas (UI auth)
  test_project_ownership.py   # two-user isolation via /api/projects (UI auth)
  test_guest_project_cleanup.py
  test_guest_flag.py          # ALLOW_GUEST_LOGIN toggle
  test_no_project_menu.py     # File-menu UI in --no-project mode (CURIO_NO_PROJECT=1)
  test_share_link.py          # share URL: owner creates, second context visits read-only
  test_shared_guest_workspace.py  # guest workspace shared across browser contexts
  test_examples.py            # structural drift check on docs/examples (no browser)
  test_dataset_palette.py     # computed dataset shows in the dataset palette and persists
  test_node_catalog.py        # Node Catalog drawer: list, search, add/remove -> palette
  test_data_catalog.py        # Data Catalog drawer: hub datasets, search, add/remove, import
  test_agent_catalog.py       # Agent Catalog drawer: list, search, add -> palette, requiresAgents closure
  test_agent_runs_e2e.py      # EVERY built-in agent: install -> attach -> run a scripted turn (NO browser)
  test_agent_chat_e2e.py      # one chat-panel baseline screenshot per agent + the review-card Apply
  test_dataset_export.py      # Data Catalog detail panel -> Export: the downloaded name and bytes
  test_dataset_lineage_e2e.py # one edge -> the dataset's lineage grows (panel, card badge, server)
  test_computed_json_output_e2e.py # dict/scalar node output installs as json, no warning (#180)
  test_data_pool_scroll_e2e.py     # the Data Pool node scrolls its own rows (#156)
  test_package_export_import.py   # palette export download -> re-import (dup + renamed clone)
  test_save_as_package.py     # node -> Save as package -> Export -> load back
  test_canvas_authoring_e2e.py     # build by hand: dataset -> drag -> connect -> run
  test_merge_flow_authoring_e2e.py # palette-dragged Merge Flow feeds `arg` downstream (#159)
  test_canvas_delete_key_e2e.py    # Delete and Backspace both delete; neither does inside Monaco (#153)
  test_autark_grammar_edit_e2e.py  # a mid-document grammar edit sticks on the first keystroke (#157)
  test_project_page_scroll_e2e.py  # the projects grid scrolls inside the viewport (#161) - no canvas
  test_global_imports_e2e.py       # an upstream import reaches downstream; np/wkt need none (#158)
  test_uhvi_install_e2e.py         # the UHVI package installs next to curio.builtin (#154)
  test_example_docs_parity.py      # examples vs their walkthroughs and README (#148) - no browser
  test_spa_deep_link_e2e.py   # a dotted deep link boots the app on the PRODUCTION static server
                              # (needs a built dist/; FAILS rather than skips without one)
  test_library_manager_e2e.py      # Installed-libraries modal -> a node imports the lib
  test_package_roundtrip_e2e.py    # canvas node -> package -> archive -> import -> run it
  test_package_metadata_roundtrip_e2e.py  # Node settings + package metadata survive the archive
  test_workflow_deps_e2e.py   # loading a dataflow auto-installs its declared packages
  test_library_install_integration.py  # library install -> sandbox import (NO browser)
  tour.py                     # screencast toolkit: caption/cursor overlay, pacing, video output
  test_feature_tour_video.py  # records the feature-tour screencast (CURIO_TOUR=1; not a test)
  stress.py                   # stress harness: issue probe, step wrapper, report writer
  test_stress_tour_video.py   # records the six-chapter stress screencast (CURIO_STRESS=1)
```

Four of these deliberately do not drive a browser. `test_examples.py` is a
structural check on the bundled dataflow JSON, and `test_example_docs_parity.py`
is its documentation counterpart - it holds each example's walkthrough and its
`docs/README.md` row to what the JSON actually contains, comparing parsed
structures rather than text so the prose can stay hand-condensed.
`test_library_install_integration.py` requests no `page` fixture: it lives here
only to reuse `curio_servers` / `current_server` / `sandbox_server`, and isolates
the backend-to-sandbox process boundary from every UI concern, so a failure says
immediately which half broke.
`test_agent_runs_e2e.py` requests no `page` fixture for the same reason, and is
described under **Agent runs** below.

## CURIO_NO_PROJECT-mode tests

The suite has two configurations with mutually-exclusive UI surfaces:

- **default** (`CURIO_NO_PROJECT=0`, the implicit value): the SPA exposes a per-user `/projects` page and the File menu offers `New dataflow` / `Load dataflow` / `Save dataflow` / `Save dataflow as` / `Export as notebook` / `Go to projects`.
- **no-project** (`CURIO_NO_PROJECT=1`): the SPA auto-guest-signs in, routes `/` directly to `/dataflow`, and hides only the project-backed entries (`Save dataflow` and `Go to projects`); `New dataflow`, `Load dataflow`, `Save dataflow as`, and `Export as notebook` remain visible.

Tests that depend on either surface call `require_project_page()` / `require_no_project_mode()` from [`utils.py`](utils.py) (both consult the live backend's `/api/config/public` so the pytest process and the `curio start` subprocess never disagree). To exercise the no-project UI explicitly:

```bash
CURIO_NO_PROJECT=1 pytest \
    utk_curio/backend/tests/test_frontend/test_no_project_menu.py \
    utk_curio/backend/tests/test_frontend/test_alive.py
```

`fixtures.py::curio_servers` reads `CURIO_NO_PROJECT` from the pytest env and forwards `--no-project` to `curio.py start`, so no extra wiring is needed.

## Catalog surfaces

**No seeding is needed.** All three catalogs are live scans of committed
content: the Node Catalog reads `<repo_root>/packages/`, the Data Catalog reads
`<repo_root>/datasets/` (surfacing as `origin: "hub"`), and the Agent Catalog
reads the built-in roster in `app/agents/builtin.py`. A fresh test user already
sees five packages, three datasets and twenty-one agents.

**Only `curio.example-ui@1` may be installed in a test.** It declares no python
dependencies, so nothing shells out to pip. `curio.weather@1`,
`ai.urbanlab.uhvi@1` and `curio.streetvision@1` pull rasterio / geopandas /
**torch** through a synchronous call capped at 30 minutes - and worse, the
resulting user-store copy makes *every later* `curio start` re-resolve those deps
(`main.py` walks every user store on boot and `sys.exit(1)`s if pip fails). The
e2e suite cannot stub pip: it runs in the backend subprocess, not the pytest
process. Guard the install endpoint with `page.route` so a mis-targeted click
fails in milliseconds instead.

Other things that surprise people here:

- **"Installed" in a drawer means the project lockfile**, not the user store. A
  fresh project therefore always offers `Add to project`, even though
  `.curio/users/*/packages/` persists across runs.
- `curio.builtin@*` is always treated as installed and offers **no** buttons: it
  ships with every instance and can be neither uninstalled nor published.
- **Export is palette-only** and gated to (user store ∩ project lockfile) minus
  builtin. The drawer's `MyPackagesList` also renders an export control.
- **A plain re-import is expected to 400.** `onPickArchive` never sets
  `replace`, and no UI path does, so re-importing an installed coordinate fails
  by design. Rename the manifest `id` to fork it instead.
- The **"In project" tab renders `MyPackagesList`, not `PackageCard`**, so the
  `data-pkg-dir` attribute is absent there; key on the row's `Remove {name}`
  aria-label.
- Card roots carry `data-pkg-dir` / `data-dataset-id` / `data-agent-coord`.
  Prefer them over display copy, which has been renamed repeatedly.
- **Every catalog confirms an add and a remove, with an in-app dialog** (#196,
  #197). `window.confirm` is gone from all three drawers, so `page.on("dialog",
  ...)` never fires for them - a test still written that way clicks the card
  button, silently does nothing, and fails later for the wrong reason. Use
  `utils.accept_confirm_dialog(page, title=..., button=...)`, and note the
  ordering: the card click only *opens* the dialog, so the request to wait on
  is triggered by the confirm, not by the click. The Node catalog keeps its
  richer `InstallPermissionsDialog` for adds (permissions + dependency
  conflicts); Data and Agent use the plain ConfirmDialog.
- **`get_by_role("dialog")` is ambiguous while a drawer is open.** The drawers
  are themselves `role="dialog"`, so scope by accessible name -
  `page.get_by_role("dialog", name="Remove Node Explainer?")` - which
  ConfirmDialog wires from its heading via `aria-labelledby`.
- **The unsaved-changes guards in `UpMenu` are still native**, so the tours'
  blanket `page.on("dialog", lambda d: d.accept())` is still required for
  File > New dataflow. Do not remove it.
- **The agent palette's footer used to sit below the fold at 1280x720.** Its
  panel hung down from its own trigger, which is the third and lowest in the
  rail, so `Browse Agent Catalog +` (how the Node suite enters) was off screen.
  That was a missed conversion rather than a viewport limit: the Datasets and
  Packages panels became `position: absolute; top: 0; left: 100%` when the
  palettes moved into the rail, and the Agent Catalog arrived later without the
  matching CSS. `paletteShell.module.css` now positions it the same way, so the
  footer is reachable and either entry point works. Reaching the drawer from the
  **Data** menu is still fine, and is what the tour does.
- **`packagesApi` percent-encodes the dirName**, so the `@` in
  `curio.canvas.draft.<slug>@1` reaches the wire as `%40`. An
  `expect_response` predicate built from the raw dirName never fires; match on
  the method and a path prefix instead.
- **Two authoring fields are write-only and cannot be round-tripped.**
  `#pkg-meta-runtime` (`compatibility.curioRuntime`) is not carried on
  `PackagePayload`, so `PackageMetadataModal` opens it blank every time and a
  reopened modal can never show what was saved. The Node settings modal's
  `Provenance tab` checkbox is canvas-local:
  `applyCanvasTemplateConfigToTemplateDraft` does not copy `hasProvenance` into
  the template draft and `toApiPayload` emits no such manifest field. Asserting
  it through an archive fails for reasons that have nothing to do with the
  archive. (The Explanation tab it used to sit beside is gone;
  `agent.node-explainer` replaced it.)
- **Node settings port rows have no label, id or test id**, and their class
  names are hashed CSS modules. Locate the section by its heading text and step
  up one level (`get_by_text("Input ports", exact=True).locator("xpath=..")`),
  then index `input` / `select` per row.
- **The Node settings -> Save As handoff crosses a store sync.** Node settings'
  `onSave` calls `updateDataNode` and `setSaveAsOpen(true)` in one batch, but
  `updateDataNode` writes FlowProvider's `useNodesState` array, which reaches
  React Flow's store only when its prop-sync effect runs - after the render
  where `show` flips true. `NodeSaveAsModal` used to `useMemo` the node on
  `[show, nodeId, getNodes]` and so packaged the pre-edit one, dropping every
  edit; it now selects off the store with `useStore`. Guarded by
  `test_package_metadata_roundtrip_e2e.py::test_node_settings_configuration_reaches_the_saved_package`
  and, in milliseconds, by `src/tests/components/nodeSaveAsModalNodeSource.test.tsx`.
  Worth knowing when reading `test_package_roundtrip_e2e.py`, which sets its
  labels through the node header pencil in a *separate* interaction and so never
  exercises the same-batch handoff.
- Palette kind rows carry `data-pkg-template-id` - the same descriptor id the
  row writes into `dataTransfer`, so addressing a row and dropping that kind
  cannot drift apart. Canvas nodes carry `data-curio-node-status`
  (`idle` / `running` / `done` / `error`) and `data-curio-node-output` on the
  inline output box. The last one matters: `.nowheel.nodrag` is on the editor
  wrapper too, so a `.first` match there returns Monaco's rendered code.

## Agent runs

`test_agent_catalog.py` covers the drawer and the palette but never runs a turn.
These two modules run one, for **every** built-in agent, and both parametrize
over `app/agents/builtin.py::BUILTIN_AGENTS` directly - add a roster entry and it
is covered on the next run, or it fails. `test_agent_runs_e2e.py` also asserts
that the parametrized set equals what `GET /api/agents/catalog` serves, so an
agent arriving by some other path cannot slip past.

| Module | Browser | What it is for |
|---|---|---|
| `test_agent_runs_e2e.py` | no | The correctness gate: install -> attach -> run -> the reply, the minted proposal or tool round, and the persisted transcript. ~1-2 s per agent. |
| `test_agent_chat_e2e.py` | yes | Drives a real chat turn per agent and captures the baselines below. A mutate-capable agent additionally **applies its proposal and is held to the canvas actually changing**; a report-only one is held to the canvas NOT changing. |

**What gets captured, and why it differs by agent.** Only 4 of the 21 built-ins
can mutate anything - the rest are `report-only` by contract - so there are two
kinds of evidence and two capture shapes.

| Agent kind | Baselines under `agent-run` | The assertion behind it |
|---|---|---|
| report-only (17) | `<agent-id>.png` - the chat panel, clipped | the reply rendered, and the saved dataflow is byte-identical afterwards |
| mutate-capable (4) | `<agent-id>_chat.png` (panel) + `<agent-id>.png` (full canvas) | the proposal was applied and the node was really created or rewritten, on the server *and* on the canvas |

Three things about those captures are deliberate:

- **The report-only baseline is clipped to the panel** (`clip_selector` on
  `save_workflow_test_screenshot`). A full-page capture was more than half
  canvas and left rail - nothing about the agent - and worse, it diluted the
  comparison: a regression inside the panel had to move 20 % of a frame it only
  partly occupies before the diff would notice.
- **The mutate baseline closes the chat panel first.** `fitView` spreads nodes
  across the whole viewport while the panel covers its right ~44 %, so the node
  the agent just created sits behind it - the canvas is the evidence, and it has
  to be in frame to be evidence.
- **A screenshot is never the only check.** A missing baseline is written and
  passed, so an error banner or an empty transcript would become "expected
  output" as quietly as a good capture. Every parameter asserts the outcome
  first, and the PNGs still want reviewing by eye before they are committed.

**No LLM, no key, no network.** `api_type == "testing"` dispatches to the
scripted provider in [`app/agents/testing_provider.py`](../../app/agents/testing_provider.py),
which pops replies off an in-process FIFO and records every message list it was
handed. Three things make that usable from a test:

| Step | How |
|---|---|
| Point the user at it | `use_scripted_llm(backend, token)` - a real `PATCH /api/auth/me` writing `llm_api_type: "testing"`, so the production `resolve_provider_config` path is the one under test |
| Script the replies | `script_agent_replies(backend, *replies)` -> `POST /api/testing/agent-script`. One entry **per provider call**: a reply carrying a `toolRequest` tail is answered by the runtime and the model is prompted again, so script the follow-up too |
| Read what reached the model | `captured_system_prompt(backend)` / `captured_agent_prompts(backend)` -> `GET /api/testing/agent-script` |

The `agent-script` routes 404 unless `CURIO_TESTING` is set, on top of the
production guard every route in that blueprint carries - unlike `stub-login`,
they read prompt text back out of the process.

Things worth knowing before adding to these:

- **The scripted reply proves nothing about *which* agent ran** - it is the same
  string for every parameter. The per-agent claim is on the captured system
  prompt, which the run composes from that agent's own preamble + instruction
  bytes. Keep that assertion or the parametrization becomes decoration.
- **Never script `web.search` / `web.fetch`.** `agent.node-researcher` and
  `agent.researcher` declare them and `app/agents/egress.py` really opens
  sockets. Both also declare a local read tool, which is what the suite uses.
- **Only three mutate tools are minted here**, and `MINTABLE_TOOLS` is ordered
  most-specific-first because an agent that declares several gets the first
  match: `dataflow.plan.write` (so the Dataflow Builder plans rather than
  creating one node), then `node.create` (applying it puts a NEW node on the
  canvas - the most visible proof an agent did something), then
  `node.content.write`. That spread is intentional: one plan, two node
  creations, one content replacement. The remaining mutate contracts
  (`dataset.install`, `package.install`, `package.draft.apply`,
  `node.template.create`) each need a real catalog row, or a run of the isolated
  build service; their mints are covered in-process by
  `test_agents/test_routes.py`, and an agent declaring only those falls through
  to the read-tool leg.
- **A plan is applied per node**, through the planned row's own
  `Create node <title>` button and the `apply-node` route - not the card's
  single `Apply`.
- **The transcript's vocabulary is `{"role": "user"|"agent", "text": ...}`.**
  `assistant` exists only in the provider-context mapping in `sessions.py`.
- **`TestAgentChatGallery` is in `fixtures.py::_SHARED_SESSION_CLASSES`**, so the
  DB is not truncated between its parameters - it logs in once and each
  parameter stubs its own *project*. A reset would invalidate the stub user's
  token while the browser still holds the cookie.
- Two things inside a capture vary run to run and the 20 % budget absorbs both:
  the run-status line's wall-clock duration, and the session id in the panel
  header. Token counts do not vary (`DEFAULT_USAGE` is fixed), so
  `2 calls x 46 = 92 tokens` is stable for a one-tool-round turn.

**One run at a time.** Two concurrent E2E runs share ports 5002/2000/8080 *and*
`.curio/test/urban_workflow_test.db`, so the second one's autouse
`e2e_clean_db` truncates `user_session` out from under the first, which then
fails with a 401 wherever it happens to be. It looks exactly like a flaky test
and is not one.

## Libraries

`test_library_install_integration.py` **really runs pip**, so it needs network
access to PyPI and skips (rather than fails) when the index is unreachable.

- **JS library install does not exist.** `POST /api/packages/libraries` with
  `kind: "js"` returns 501, as does the DELETE. There is no npm runner; JS nodes
  resolve imports only against `<repo_root>/node_modules`, populated by
  `npm install` at launch.
- **Only a library outside the sandbox's `_globals_cache` can demonstrate a
  fresh import.** Anything in that cache (`pandas`, `geopandas`, the DuckDB
  helpers, …) is already in `sys.modules` for the sandbox's lifetime. The tests
  use `inflection`: pure Python, zero dependencies, never preloaded.
  `test_library_manager_e2e.py` uses `titlecase` for the same reasons and
  deliberately a *different* library, so the two cannot poison each other's
  negative control within one server session.
- **Not repeat-safe.** Teardown pip-uninstalls the library, but
  `sys.modules['inflection']` stays warm in the still-running sandbox, so the
  negative control cannot be re-armed within one server session. Restart the
  servers between runs.
- A library install is importable by the next node execution with **no sandbox
  restart**: backend and sandbox launch from the same `sys.executable`, so pip
  writes into the site-packages the sandbox already imports from.

## Cleaning up after a test

`/api/testing/reset-db` truncates SQL tables only, while `.curio/users/<id>/`
persists - and `user.id` is a bare sqlite rowid alias, so ids recycle from 1.
A test that installs a package, imports a dataset or adds a library therefore
leaks into the *next* test's view of a "fresh" user unless it cleans up.

Use a **non-autouse** yield fixture and request it explicitly: the autouse
`e2e_clean_db` finalizes *last*, so an explicitly-requested fixture still has a
live stub user (and a valid token) to authenticate its DELETE calls with. Go
through the real routes rather than deleting files - for libraries that matters,
because the route runs in the backend process, the only interpreter guaranteed to
match the sandbox's.

## Feature-tour screencast

`test_feature_tour_video.py` is not a test. It borrows this harness - the stack
boot, the WebGPU-capable Chrome, the canvas helpers - to record a narrated
screencast of Curio's features, and it is skipped unless `CURIO_TOUR=1`, so a
normal suite run never pays for it.

```bash
# from utk_curio/backend, with PYTHONPATH=<repo root>
CURIO_TOUR=1 pytest tests/test_frontend/test_feature_tour_video.py -s

# re-record two scenes, slower
CURIO_TOUR=1 CURIO_TOUR_SCENES=linkedviews,dashboard CURIO_TOUR_SPEED=0.8 \
  pytest tests/test_frontend/test_feature_tour_video.py -s
```

The take is one continuous Playwright recording of a single page, so the whole
tour runs in one browser session: signup, the projects page, configuring the AI
provider, authoring a dataflow from a catalog dataset, dataset lineage, the Node
Catalog, the Agent Catalog, attaching and running an agent, Vega-Lite views,
dashboard mode, provenance, linked interactions, an Autark/WebGPU map, and the
catalog pages. Captions, a synthetic cursor and the spotlight ring come
from [`tour.py`](tour.py), which paints them into the page above the app -
Playwright records the page and nothing else, so a real pointer would be
invisible and a click would look unmotivated.

### The agent scenes need a provider

`aisettings` types a base URL, an API key and a model into AI Settings on
camera, and `agentrun` then asks that endpoint a real question. Curio ships no
provider of its own and the tour's account starts with none, so this is
load-bearing rather than decorative.

The endpoint and model default to the `LLM_*` constants at the top of the
module. **The key is not a constant** — put it in `.curio/tour-provider.json`
(`.curio/` is gitignored) or in `CURIO_TOUR_LLM_API_KEY`:

```json
{ "baseUrl": "https://…/", "model": "…", "apiKey": "sk-…" }
```

Without a key both scenes still record: they show the panel and the chat, say so
in a caption, and skip the call. Filming an agent that visibly errors is worse
than filming one that admits it is unconfigured. `agentrun` is the only scene
that leaves the machine, which makes it the one most likely to be the scene that
failed.

| Variable | Purpose |
|---|---|
| `CURIO_TOUR` | Must be `1`; the module skips otherwise. |
| `CURIO_TOUR_SCENES` | Comma-separated scene ids (see `SCENES`); default all. A subset that starts mid-tour stub-logs-in and opens a scratch dataflow first. |
| `CURIO_TOUR_OUT` | Output directory (default `.curio/tour/`, which is gitignored). |
| `CURIO_TOUR_SPEED` | Pacing multiplier: `2` halves every hold, `0.8` lengthens them. Caption holds are derived from their word count, so this scales reading time too. |

Output is `curio-feature-tour.webm`. An `.mp4` is written alongside it when a
**system** ffmpeg is on `PATH`; Playwright's bundled ffmpeg is compiled down to
vp8/webm and cannot do it. A scene that raises is reported (with a
`failed-<scene>.png` next to the video) and the tour continues, so one broken
step costs a chapter rather than the whole take - the run then fails at the end
naming the scenes that broke.

## Stress-test screencast

`test_stress_tour_video.py` is the feature tour's adversarial sibling, and like
it, it is not a test. Where the tour shows each feature's happy path once, this
walks *everything* - every built-in and catalog node type, every catalog
dataset, every built-in agent - and deliberately takes the paths that are
supposed to refuse: an output wired to an output, a cycle, a node whose body
raises, a re-imported archive. It is skipped unless `CURIO_STRESS=1`.

```bash
# from utk_curio/backend, with PYTHONPATH=<repo root>
CURIO_STRESS=1 pytest tests/test_frontend/test_stress_tour_video.py -s -v

# one chapter, at the tour's pace instead of the stress default of 1.6x
CURIO_STRESS=1 CURIO_STRESS_CHAPTERS=agents CURIO_STRESS_SPEED=1.0   pytest tests/test_frontend/test_stress_tour_video.py -s
```

Six chapters, six recordings, **one pytest session** - the session-scoped
`curio_servers` fixture boots the stack once and owns its lifecycle. Run
`bash scripts/kill-curio.sh` first: an orphaned backend holds the test sqlite
file and the next run dies at conftest import with `PermissionError: [WinError
32]`.

| Chapter | What it drives |
|---|---|
| `access` | signup validation, real signup, the persona picker, sign out, a wrong password, sign in; the projects page - search, the two status tabs, all three sorts, grid/list, card click / Enter / Space / right-click, Duplicate, Rename, Delete, the detail drawer; Jupyter notebook import |
| `canvas` | all twelve built-in tiles dropped and identity-checked; header band, resize, comments, pin; every editor tab; Node settings including the port editor; invalid connections and cycles; the guarded delete; Backspace inside Monaco; box select; zoom; minimize/expand all; a node that raises; Play All; Save-as JSON and notebook export |
| `nodes` | the Node Catalog drawer's four tabs; **a real install of every catalog package** (`curio.weather`, `ai.urbanlab.uhvi`, `curio.streetvision` each shell out to pip); every template those packages ship dropped onto the canvas; **authoring a new node type** through Node settings -> Save as package node -> a new package, then dragging it back out of the palette; package metadata; export, re-import (400 by design), the library manager (a real `titlecase` install, then a JS install that 501s) |
| `data` | the Data Catalog drawer's four tabs; **every hub dataset added to the dataflow**; the detail panel's four tabs; **a real import of every format** - CSV, Parquet, GeoJSON, GeoTIFF, an OSM PBF (split per layer) and a shapefile the chapter synthesises, since the repo ships none; dataset drag to canvas; a computed dataset and its lineage; the catalog pages and a deliberately bad dataset id |
| `agents` | AI Settings from both of its entry points, all four provider tabs, Fetch models, the HF token; **every agent in the catalog installed**; all three attach targets (node, connection, canvas); the chat panel's controls; **one live turn per attached agent** against the configured provider; applying a proposal |
| `views` | all eleven bundled examples loaded and run, Autark/WebGPU among them; linked brushing; the Data Pool scroll; Merge Flow; JS Computation; widgets; dashboard mode with its lock; the provenance window and a node's provenance tab; the in-app intro.js tutorial |

### What it produces

Output goes to `.curio/stress/` (gitignored), overridable with
`CURIO_STRESS_OUT`:

- `curio-stress-<chapter>.webm`, one per chapter. An `.mp4` lands beside each
  only when a **system** ffmpeg is on `PATH` - Playwright's bundled build is
  compiled down to vp8/webm and cannot do it.
- `<chapter>/` - screenshots, named for the step that took them, plus that
  chapter's `issues.json`.
- `ISSUES.md` and a merged `issues.json`, written by a class-scoped fixture once
  every selected chapter has run.

Every row in `ISSUES.md` is a **lead, not a verified defect**. `stress.Probe`
reports what the app said - console errors, uncaught page errors, failed
requests, 4xx/5xx responses, error and warning toasts (caught with a
MutationObserver, because `showToast` removes each one after 5 s) - plus any
node that finished red and any step that raised. Each carries the `mm:ss` offset
into its chapter's recording, so the moment can be watched rather than
reconstructed. `stress.EXPECTED` filters out what the app is documented to do
(the re-import 400, the JS-library 501, webpack chatter); those are still
exercised, still on camera, and logged to stdout so a rule that starts
swallowing a real regression can be spotted.

`StressRun.step` is the unit: it captions the step on camera, times it, catches
whatever it raises, screenshots the moment, and attributes the probe's output to
it. **A broken step never ends the chapter**, and a broken chapter never loses
the recording - `_record` finalizes the video in a `finally`.

### Two things to know before running it

- **It installs packages and libraries for real.** When pytest owns the stack,
  `tests/conftest.py` sets `CURIO_LAUNCH_CWD` to the **repo root**, so user
  package stores land in `<repo>/.curio/users/<id>/` - and `main.py` walks every
  user store on boot and `sys.exit(1)`s if pip cannot re-resolve one. Budget
  10-25 minutes for the torch install in `nodes`, and check that
  `python curio.py start` still boots afterwards.
- **The agent chapter needs a provider.** It reads
  `.curio/tour-provider.json` or `CURIO_TOUR_LLM_*`, the same way the feature
  tour does, so no credential is ever committed. Without a key it records the
  surfaces, says so on camera, and skips the turns.

The class is listed in `fixtures._SHARED_SESSION_CLASSES`: chapter `access`
signs one account up through the real form and the other five keep using it, so
the autouse `e2e_clean_db` must not truncate between them.


## Environment Variables

| Variable | Purpose |
|---|---|
| `CURIO_E2E_WORKFLOWS` | Comma-separated workflow basenames to run (default: all) |
| `CURIO_E2E_USE_EXISTING` | Set to `1` to skip server startup and use running servers. Those servers **must** carry `CURIO_TESTING=1` or every `/api/testing/*` call 404s and the autouse `e2e_clean_db` fixture errors on setup; the CI overlays (`docker-compose.ci.yml`, `docker-compose.ci-isolated.yml`) and `scripts/test.sh` set it. `scripts/test.sh` also exports this variable for its whole run, so the backend unit suite does not claim ownership of a DB the running stack is serving from. |
| `CURIO_E2E_HOST` | Host for existing servers (default: `localhost`) |
| `CURIO_E2E_BACKEND_PORT` | Backend port for existing servers (default: `5002`) |
| `CURIO_E2E_SANDBOX_PORT` | Sandbox port for existing servers (default: `2000`). Reaches both the `/live` wait in `e2e_existing_servers` **and** the two helpers that call the sandbox directly, via `utils.py::sandbox_base_url`. It used to reach only the first, so on a non-default port `load_artifact_as_dict` and `execute_workflow_programmatically` silently addressed port 2000 and every `test_node_execution` died on an unexplained `401`. |
| `CURIO_SANDBOX_TOKEN` | The sandbox's shared secret for `/exec`, `/execJs`, `/get` and `/install` (`sandbox/app/auth.py`). The self-managed path mints one and publishes it to this process; **with `CURIO_E2E_USE_EXISTING=1` you must set it yourself, to the same value the running stack was started with** — `curio.py start` mints a random one otherwise, and nothing can recover it. A mismatch now fails with that sentence rather than a bare `401`. |
| `CURIO_E2E_FRONTEND_PORT` | Frontend port for existing servers (default: `8080`) |
| `CURIO_TESTING` | Two jobs: switches the backend to test-only DB paths under `.curio/test/`, **and** is the second factor the `/api/testing/*` blueprint and the scripted LLM provider require. Exported by `../conftest.py`; externally-booted servers (compose stacks included) must be given it explicitly. |
| `DATABASE_URL_TEST` | SQLAlchemy URL for the test DB (defaults to `sqlite:///…/.curio/test/urban_workflow_test.db`). |
| `CURIO_TEST_WORKSPACE` | Persist the per-session test workspace here instead of a temp dir (debugging). |
