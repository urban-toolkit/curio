# Frontend E2E Tests

See [CONTRIBUTING.md](../../../../docs/CONTRIBUTING.md#frontend-e2e-tests)
for the repo-wide E2E workflow. Test-specific details live here.

Playwright-based end-to-end tests that upload workflow JSON files into the Curio frontend and verify the ReactFlow canvas renders correctly.

## Run

```bash
# full suite
pytest utk_curio/backend/tests/test_frontend/

# headed (watch the browser; required for AUTK fixtures to actually render — see below)
pytest utk_curio/backend/tests/test_frontend/ --headed

# use already-running servers (e.g. docker compose); the caller is responsible for
# booting them with CURIO_TESTING=1 + DATABASE_URL pointing at the test DB
CURIO_E2E_USE_EXISTING=1 pytest utk_curio/backend/tests/test_frontend/
```

### AUTK / WebGPU note

Autark workflows use the single `AUTK_GRAMMAR` node type, which renders its map/plot via WebGPU. The `browser_type_launch_args` fixture in the **parent** [`../conftest.py`](../conftest.py) points `executable_path` at the system-installed Google Chrome and passes a minimal flag set (`--enable-unsafe-webgpu --enable-unsafe-swiftshader`). This is deliberate: Playwright's bundled Chromium on Windows ships without a working Dawn/WebGPU runtime (`requestAdapter()` returns null), whereas real Chrome 113+ returns an adapter. When Chrome can't be found it falls back to bundled Chromium.

There is **no WebGPU tolerance**: an `AUTK_GRAMMAR` node that errors (including because WebGPU is unavailable) is a hard test failure. To run the autk examples you need a browser that provides WebGPU — which the system-Chrome `executable_path` above ensures. `_webgpu_diagnostics` still probes adapter/device state once per session and attaches it to the failure dump for debugging.

`AUTK_GRAMMAR` is a `"grammar"` node (grammar/JSON editor + output tab) and exercises the full matrix: `test_node_type_and_content` checks the grammar editor; `test_node_execution` verifies each node reaches **Done**. Its grammar content (and any JavaScript/WGSL compute blocks) is excluded from the Python random-seed injection used by Python `CODE_TYPES` nodes.

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
| `CURIO_TESTING` | When `1`, backend uses test-only DB paths. Exported by [`../conftest.py`](../conftest.py) at import time, so every pytest run under `tests/` already has it. |
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
| `skip_if_shared_view(page, *, timeout=4000)` | Skips when the dataflow opened read-only as the shared guest. In a no-auth environment the browser cannot see another user's installed packages or datasets and every catalog fetch comes back empty, so the test is not meaningful - better a clear skip than a confusing failure deep inside a drawer assertion. |
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
- **`to_be_visible()` is not a gate for a drawer.** Both slide in via `transform: translate3d(100%, 0, 0)`, which keeps a full bounding box off-screen. Gate on the dataset drawer's `aria-hidden="false"` (that attribute *is* the presented signal) and let Playwright's bounding-box-stability check ride out the transform. Never `force=True` on drawer internals - `force` skips the very hit-target check that protects against clicking a mid-slide panel.
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
  `agent-catalog-drawer`,
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
  test_workflows.py           # TestWorkflowCanvas — DB-stubbed auth via loaded_workflow
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
  test_library_manager_e2e.py      # Installed-libraries modal -> a node imports the lib
  test_package_roundtrip_e2e.py    # canvas node -> package -> archive -> import -> run it
  test_package_metadata_roundtrip_e2e.py  # Node settings + package metadata survive the archive
  test_workflow_deps_e2e.py   # loading a dataflow auto-installs its declared packages
  test_library_install_integration.py  # library install -> sandbox import (NO browser)
  tour.py                     # screencast toolkit: caption/cursor overlay, pacing, video output
  test_feature_tour_video.py  # records the feature-tour screencast (CURIO_TOUR=1; not a test)
```

Three of these deliberately do not drive a browser. `test_examples.py` is a
structural check on the bundled dataflow JSON, and `test_example_docs_parity.py`
is its documentation counterpart - it holds each example's walkthrough and its
`docs/README.md` row to what the JSON actually contains, comparing parsed
structures rather than text so the prose can stay hand-condensed.
`test_library_install_integration.py` requests no `page` fixture: it lives here
only to reuse `curio_servers` / `current_server` / `sandbox_server`, and isolates
the backend-to-sandbox process boundary from every UI concern, so a failure says
immediately which half broke.

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

**No seeding is needed.** Both catalogs are live directory scans of committed
content: the Node Catalog reads `<repo_root>/packages/`, the Data Catalog reads
`<repo_root>/datasets/` (surfacing as `origin: "hub"`). A fresh test user already
sees five packages and three datasets.

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
  fresh project therefore always offers `Add to dataflow`, even though
  `.curio/users/*/packages/` persists across runs.
- `curio.builtin@*` is always treated as installed and offers **no** buttons: it
  ships with every instance and can be neither uninstalled nor published.
- **Export is palette-only** and gated to (user store ∩ project lockfile) minus
  builtin. The drawer's `MyPackagesList` also renders an export control.
- **A plain re-import is expected to 400.** `onPickArchive` never sets
  `replace`, and no UI path does, so re-importing an installed coordinate fails
  by design. Rename the manifest `id` to fork it instead.
- The **"In dataflow" tab renders `MyPackagesList`, not `PackageCard`**, so the
  `data-pkg-dir` attribute is absent there; key on the row's `Remove {name}`
  aria-label.
- Card roots carry `data-pkg-dir` / `data-dataset-id`. Prefer them over display
  copy, which has been renamed repeatedly.
- **`packagesApi` percent-encodes the dirName**, so the `@` in
  `curio.canvas.draft.<slug>@1` reaches the wire as `%40`. An
  `expect_response` predicate built from the raw dirName never fires; match on
  the method and a path prefix instead.
- **Two authoring fields are write-only and cannot be round-tripped.**
  `#pkg-meta-runtime` (`compatibility.curioRuntime`) is not carried on
  `PackagePayload`, so `PackageMetadataModal` opens it blank every time and a
  reopened modal can never show what was saved. The Node settings modal's
  `Provenance tab` / `Explanation tab` checkboxes are canvas-local:
  `applyCanvasTemplateConfigToTemplateDraft` does not copy `hasProvenance` /
  `hasExplanation` into the template draft and `toApiPayload` emits no such
  manifest field. Asserting either through an archive fails for reasons that
  have nothing to do with the archive.
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
tour runs in one browser session: signup, the projects page, authoring a
dataflow from a catalog dataset, dataset lineage, the Node Catalog, Vega-Lite
views, dashboard mode, provenance, linked interactions, an Autark/WebGPU map,
and the catalog pages. Captions, a synthetic cursor and the spotlight ring come
from [`tour.py`](tour.py), which paints them into the page above the app -
Playwright records the page and nothing else, so a real pointer would be
invisible and a click would look unmotivated.

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

## Environment Variables

| Variable | Purpose |
|---|---|
| `CURIO_E2E_WORKFLOWS` | Comma-separated workflow basenames to run (default: all) |
| `CURIO_E2E_USE_EXISTING` | Set to `1` to skip server startup and use running servers (must already be booted with `CURIO_TESTING=1`) |
| `CURIO_E2E_HOST` | Host for existing servers (default: `localhost`) |
| `CURIO_E2E_BACKEND_PORT` | Backend port for existing servers (default: `5002`) |
| `CURIO_E2E_SANDBOX_PORT` | Sandbox port for existing servers (default: `2000`) |
| `CURIO_E2E_FRONTEND_PORT` | Frontend port for existing servers (default: `8080`) |
| `CURIO_TESTING` | Switches backend to test-only DB paths under `.curio/test/`. Exported by `../conftest.py`; only externally-booted servers need it passed in explicitly. |
| `DATABASE_URL_TEST` | SQLAlchemy URL for the test DB (defaults to `sqlite:///…/.curio/test/urban_workflow_test.db`). |
| `CURIO_TEST_WORKSPACE` | Persist the per-session test workspace here instead of a temp dir (debugging). |
