#!/usr/bin/env bash
# Run the full Curio test suite locally without Docker.
#
# Starts backend, sandbox, and frontend via 'python curio.py start',
# runs all tests, then shuts everything down automatically.
#
# Usage:
#   ./scripts/test.sh [options]
#
# Options:
#   --use-existing      Skip start/stop and clean; use already-running Curio servers
#                       (export CURIO_SANDBOX_TOKEN to the value that
#                        stack was started with, or the two e2e tests
#                        calling the sandbox directly will get 401s)
#   --headed            Open a visible browser window during E2E tests
#   --videos            Also record the per-issue fix screencasts (slow)
#   --no-examples       Skip the tests that need the example dataflows seeded
#                       (on by default; the stack this script boots already
#                        starts with --with-examples)
#   --workflows A,B     Run only the named workflow files (e.g. Vega.json,Regression.json)
#   --backend-only      Run only backend unit tests
#   --sandbox-only      Run only sandbox unit tests
#   --jest-only         Run only Jest frontend unit tests
#   --e2e-only          Run only the E2E suite
#   --unit-only         Run only backend, sandbox, and frontend unit tests (no E2E)
#   --allure-dir DIR    Write Allure results to DIR (passed to E2E pytest)
#   --parallel N        Run the E2E suite on N pytest-xdist workers, each against
#                       its own backend+sandbox pair (one shared frontend).
#                       N=auto picks min(4, cores/4). Default 1, or $CURIO_E2E_PARALLEL.
#                       With --use-existing, pairs 1..N-1 must already be running
#                       on the ports `python -m utk_curio.backend.tests.shards K` prints.
#
# Ports: the stack this script boots binds BACKEND_PORT / SANDBOX_PORT /
# FRONTEND_PORT from the environment (defaults 5002 / 2000 / 8080), so a
# checkout with its own .curio-ports.sh never fights a sibling's stack.

set -uo pipefail

USE_EXISTING=0
HEADED=0
VIDEOS=0
# On by default: the stack below boots with --with-examples either way, and
# CI's compose stack does too, so the examples tests may as well run where
# they can. --no-examples is for a quick local pass that skips the seeding.
EXAMPLES=1
E2E_WORKFLOWS=""
ALLURE_DIR=""
PARALLEL="${CURIO_E2E_PARALLEL:-1}"
SUITE="all"   # all | backend | sandbox | jest | e2e | unit

while [[ $# -gt 0 ]]; do
  case $1 in
    --use-existing)  USE_EXISTING=1;       shift ;;
    --headed)        HEADED=1;             shift ;;
    --videos)        VIDEOS=1;             shift ;;
    --no-examples)   EXAMPLES=0;           shift ;;
    --workflows)     E2E_WORKFLOWS="$2";   shift 2 ;;
    --backend-only)  SUITE="backend";      shift ;;
    --sandbox-only)  SUITE="sandbox";      shift ;;
    --jest-only)     SUITE="jest";         shift ;;
    --e2e-only)      SUITE="e2e";          shift ;;
    --unit-only)     SUITE="unit";         shift ;;
    --allure-dir)    ALLURE_DIR="$2";      shift 2 ;;
    --parallel)      PARALLEL="$2";        shift 2 ;;
    --help|-h)
      sed -n '2,35p' "$0"
      exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CURIO_PID=""
SHARD_PIDS=()   # launchers of the extra backend+sandbox pairs (--parallel > 1)

# Base ports for the stack this script boots and for shard 0.
export BACKEND_PORT="${BACKEND_PORT:-5002}"
export SANDBOX_PORT="${SANDBOX_PORT:-2000}"
export FRONTEND_PORT="${FRONTEND_PORT:-8080}"
export CURIO_E2E_HOST="${CURIO_E2E_HOST:-localhost}"
export CURIO_E2E_BACKEND_PORT="${CURIO_E2E_BACKEND_PORT:-$BACKEND_PORT}"
export CURIO_E2E_SANDBOX_PORT="${CURIO_E2E_SANDBOX_PORT:-$SANDBOX_PORT}"
export CURIO_E2E_FRONTEND_PORT="${CURIO_E2E_FRONTEND_PORT:-$FRONTEND_PORT}"

if [[ "$PARALLEL" == "auto" ]]; then
  cores=$(python -c 'import os; print(os.cpu_count() or 4)')
  PARALLEL=$(( cores / 4 )); (( PARALLEL < 1 )) && PARALLEL=1; (( PARALLEL > 4 )) && PARALLEL=4
fi
if ! [[ "$PARALLEL" =~ ^[0-9]+$ ]] || (( PARALLEL < 1 )); then
  echo "ERROR: --parallel expects a positive integer or 'auto', got '$PARALLEL'" >&2; exit 1
fi

# This script NEVER lets pytest own the server lifecycle. It either attaches to
# a stack someone else booted (--use-existing) or boots one itself below and
# still runs the E2E suite with CURIO_E2E_USE_EXISTING=1. Export it for the
# WHOLE run rather than only the E2E step, because backend/tests/conftest.py
# reads it to decide whether this process owns the test DB: without it the
# backend unit run deletes .curio/test/urban_workflow_test.db at import and
# rmtrees .curio/test at session end -- out from under the live backend that is
# serving from exactly those paths (CI sets CURIO_TESTING=1 on the container,
# see docker-compose.ci.yml). Every backend unit package uses the in-memory
# sqlite:// from tests/_unit_fixtures.py, so nothing here needs that file.
export CURIO_E2E_USE_EXISTING=1

# Derived run flags
RUN_BACKEND=0; RUN_SANDBOX=0; RUN_JEST=0; RUN_E2E=0
case "$SUITE" in
  all)     RUN_BACKEND=1; RUN_SANDBOX=1; RUN_JEST=1; RUN_E2E=1 ;;
  unit)    RUN_BACKEND=1; RUN_SANDBOX=1; RUN_JEST=1 ;;
  backend) RUN_BACKEND=1 ;;
  sandbox) RUN_SANDBOX=1 ;;
  jest)    RUN_JEST=1 ;;
  e2e)     RUN_E2E=1 ;;
esac

# result tracking
RESULTS=()   # "PASS|FAIL  label" entries
OVERALL=0

# Abort immediately on a failed setup step. These are preconditions, not
# suites: continuing past a failed `npm install` or `playwright install`
# produces downstream failures whose real cause is buried, and if the
# remaining suites happen to pass the script would exit 0 despite the error.
die() {
  local label=$1 rc=$2
  if [[ $rc -ne 0 ]]; then
    RESULTS+=("  FAIL  $label (setup step, exit $rc)")
    OVERALL=1
    echo "ERROR: $label failed with exit $rc - aborting." >&2
    exit $rc
  fi
}

record() {
  local label=$1 rc=$2
  if [[ $rc -eq 0 ]]; then
    RESULTS+=("  PASS  $label")
  else
    RESULTS+=("  FAIL  $label")
    OVERALL=1
  fi
}

wait_for_port() {
  local name=$1 port=$2
  echo "==> Waiting for $name on port $port..."
  for _ in $(seq 240); do
    # Fail fast if the Curio process already exited
    if [[ -n "${CURIO_PID:-}" ]] && ! kill -0 "$CURIO_PID" 2>/dev/null; then
      echo "ERROR: Curio process (pid $CURIO_PID) exited unexpectedly while waiting for $name" >&2
      RESULTS+=("  FAIL  stack boot ($name never came up; launcher exited)"); OVERALL=1
      exit 1
    fi
    if python -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('localhost', $port)); s.close()" 2>/dev/null; then
      echo "    $name is ready."
      return
    fi
    sleep 1
  done
  echo "ERROR: $name (port $port) did not start within 240 s" >&2
  RESULTS+=("  FAIL  stack boot ($name on port $port timed out)"); OVERALL=1
  exit 1
}

# --parallel N: shards 1..N-1 are extra backend+sandbox pairs behind the ONE
# frontend the base stack serves. Ports, state dir, DuckDB, dataset-catalog copy
# and logs all come from backend/tests/shards.py -- the same module every xdist
# worker uses to find ITS pair, so driver and worker cannot disagree. Shard 0 is
# the base stack itself.
shard_facts() {   # -> "<backend port> <sandbox port> <state dir>" for shard $1
  PYTHONPATH="$REPO_ROOT" python -m utk_curio.backend.tests.shards "$1" --json \
    | python -c 'import json,sys; d=json.load(sys.stdin); print(d["CURIO_E2E_BACKEND_PORT"], d["CURIO_E2E_SANDBOX_PORT"], d["CURIO_STATE_DIR"])'
}
start_extra_shards() {
  local k bport sport state
  for (( k = 1; k < PARALLEL; k++ )); do
    read -r bport sport state < <(shard_facts "$k")
    echo "==> Starting shard $k: backend $bport, sandbox $sport, state $state"
    rm -rf "$state"
    (
      eval "$(PYTHONPATH="$REPO_ROOT" python -m utk_curio.backend.tests.shards "$k")"
      mkdir -p "$CURIO_CATALOG_ROOT" "$CURIO_SHARED_DATA"
      # A COPY, not an empty dir: the catalog tests assert the shipped datasets exist.
      cp -r "$REPO_ROOT/datasets/." "$CURIO_CATALOG_ROOT/"
      export CURIO_NO_OPEN=1 FLASK_USE_RELOADER=0 CURIO_DEV=1
      python "$REPO_ROOT/curio.py" start backend --auth --with-examples \
        --backend-port "$BACKEND_PORT" --sandbox-port "$SANDBOX_PORT" \
        > "$CURIO_STATE_DIR/launch-backend.out" 2>&1 &
      echo $! > "$CURIO_STATE_DIR/backend.pid"
      python "$REPO_ROOT/curio.py" start sandbox \
        --backend-port "$BACKEND_PORT" --sandbox-port "$SANDBOX_PORT" \
        > "$CURIO_STATE_DIR/launch-sandbox.out" 2>&1 &
      echo $! > "$CURIO_STATE_DIR/sandbox.pid"
    )
    SHARD_PIDS+=("$(cat "$state/backend.pid")" "$(cat "$state/sandbox.pid")")
  done
  for (( k = 1; k < PARALLEL; k++ )); do
    read -r bport sport state < <(shard_facts "$k")
    wait_for_port "shard $k backend" "$bport"
    wait_for_port "shard $k sandbox" "$sport"
  done
}

# Stop everything this script started -- and nothing else. Two mechanisms,
# because on Windows/MSYS the `$!` of a backgrounded launcher is an MSYS pid
# that taskkill does not know, so a PID-based kill silently leaves the whole
# server tree running (observed: every port still serving after "cleanup").
#   1. by PORT, through the launcher's own _kill_port (what `curio.py start`
#      uses to claim a port), for the base triple and every shard pair;
#   2. by COMMAND LINE scoped to THIS checkout's path, for the launcher
#      processes themselves -- never by process name, which would take down a
#      sibling checkout's stack on the same machine.
stop_own_stacks() {
  local ports=("$BACKEND_PORT" "$SANDBOX_PORT" "$FRONTEND_PORT") k bport sport state
  for (( k = 1; k < PARALLEL; k++ )); do
    read -r bport sport state < <(shard_facts "$k") && ports+=("$bport" "$sport")
  done
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
      powershell -NoProfile -Command "
        Get-CimInstance Win32_Process | Where-Object {
          \$_.CommandLine -match [regex]::Escape('$(basename "$REPO_ROOT")') -and
          ((\$_.Name -eq 'python.exe' -and \$_.CommandLine -match 'curio.py start') -or
           (\$_.Name -eq 'node.exe' -and \$_.CommandLine -match 'webpack'))
        } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" >/dev/null 2>&1 || true
      ;;
    *)
      pkill -f "$REPO_ROOT/curio.py start" 2>/dev/null || true
      ;;
  esac
  PYTHONPATH="$REPO_ROOT" python - "${ports[@]}" <<'PY' >/dev/null 2>&1 || true
import sys
from utk_curio.main import _kill_port
for port in sys.argv[1:]:
    _kill_port(int(port))
PY
}

cleanup() {
  if [[ -n "$CURIO_PID" || ${#SHARD_PIDS[@]} -gt 0 ]]; then
    echo ""
    echo "==> Stopping the stack(s) this run started..."
    stop_own_stacks
  fi
  if [[ -n "$CURIO_PID" ]]; then
    echo ""
    echo "==> Stopping Curio (pid $CURIO_PID) and its server tree..."
    # 'curio.py start' only supervises: backend.server, sandbox.server and the
    # npm -> webpack chain are separate processes. Killing the supervisor alone
    # orphans all of them, and they keep holding :5002/:2000/:8080 - so the next
    # run either fails to bind or, worse, silently tests the stale servers left
    # listening from this one.
    case "$(uname -s)" in
      MINGW*|MSYS*|CYGWIN*)
        # /T walks parent-PID links, so the supervisor has to still be alive
        # when we ask - kill the tree first, never the root first.
        # MSYS2_ARG_CONV_EXCL stops MSYS rewriting the flags as paths, so the
        # switches are passed with single slashes. Do NOT also double them:
        # with conversion disabled '//PID' reaches taskkill verbatim and errors.
        MSYS2_ARG_CONV_EXCL='*' taskkill /PID "$CURIO_PID" /T /F >/dev/null 2>&1 || true
        ;;
      *)
        # Launched under 'set -m', so the job leads its own process group and a
        # negative pid signals every descendant. Fall back to the bare pid if
        # the group is already gone.
        kill -TERM "-$CURIO_PID" 2>/dev/null || kill -TERM "$CURIO_PID" 2>/dev/null || true
        sleep 2
        kill -KILL "-$CURIO_PID" 2>/dev/null || true
        ;;
    esac
    # Bounded: the tree is already down; a launcher taskkill could not see
    # would otherwise hang this wait forever.
    for _ in $(seq 20); do kill -0 "$CURIO_PID" 2>/dev/null || break; sleep 0.5; done
  fi

  # Print summary
  echo ""
  echo "========================================"
  echo "  Test Summary"
  echo "========================================"
  for r in "${RESULTS[@]+"${RESULTS[@]}"}"; do
    echo "$r"
  done
  echo "----------------------------------------"
  if [[ $OVERALL -eq 0 ]]; then
    echo "  All tests passed."
  else
    echo "  Some tests FAILED. See output above."
  fi
  echo "========================================"
}

# ---------------------------------------------------------------------------
# 1. Clean all build artifacts and runtime data (skipped when using existing services)
# ---------------------------------------------------------------------------
if [[ $USE_EXISTING -eq 0 ]]; then
  bash "$REPO_ROOT/scripts/clean.sh"
  die "clean.sh" $?
fi

# ---------------------------------------------------------------------------
# 2. Install dependencies (needed by both unit tests and E2E)
# ---------------------------------------------------------------------------
echo "==> Installing Python dependencies..."
pip install -r "$REPO_ROOT/requirements.txt" -q
die "pip install -r requirements.txt" $?

echo "==> Installing manifest python deps via curio setup..."
PYTHONPATH="$REPO_ROOT" python "$REPO_ROOT/curio.py" setup
die "curio.py setup" $?

if [[ $USE_EXISTING -eq 0 ]]; then
  echo "==> Installing frontend npm dependencies..."
  (cd "$REPO_ROOT/utk_curio/frontend/urban-workflows" && npm install -q)
  die "npm install" $?
fi

# ---------------------------------------------------------------------------
# 3. Start Curio services (backend :5002, sandbox :2000, frontend :8080)
# ---------------------------------------------------------------------------
if [[ $USE_EXISTING -eq 0 ]]; then
  echo "==> Starting Curio services..."
  trap cleanup EXIT INT TERM
  # Pin CURIO_LAUNCH_CWD to the repo root so the sandbox resolves data files
  # referenced by relative path (e.g. DATA_LOADING reading
  # docs/examples/data/*.geojson) regardless of where test.sh was invoked
  # from. curio.py start falls back to os.getcwd() otherwise (main.py).
  #
  # CURIO_DEV=1 serves the frontend via the webpack dev server (compiled from
  # source) rather than the prebuilt static dist/, so the E2E suite always
  # tests the current frontend — matching how the e2e curio_servers fixture
  # boots. Without it a stale dist/ hides in-tree frontend changes.
  # Job control on for the launch only: it puts the background job in its own
  # process group so cleanup() can signal the whole server tree by negative pid
  # on POSIX. Without it the job shares this script's group and a group-kill
  # would take the script down with it.
  # Pin the sandbox shared secret. The sandbox requires it on /exec,
  # /execJs, /get and /install (utk_curio/sandbox/app/auth.py), and
  # 'curio.py start' would otherwise mint a random one into the server's
  # environment only, which this script and the pytest process could not
  # then read. Two e2e tests call the sandbox directly. main.py honours a
  # pre-set value.
  export CURIO_SANDBOX_TOKEN="${CURIO_SANDBOX_TOKEN:-$(python -c 'import secrets; print(secrets.token_urlsafe(32))')}"
  # --auth is REQUIRED, not optional. The E2E suite exercises the real signup /
  # signin / guest flows and most of it acts as an authenticated OWNER: a
  # dataflow's own packages, datasets and agents are visible only to the user
  # who installed them. Booted without it, 'curio.py start' sets
  # CURIO_NO_AUTH=1, the browser is the read-only shared guest, every catalog
  # fetch comes back empty, and 43 tests - the whole agent-catalog suite among
  # them - skipped instead of running, so a green run proved far less than it
  # appeared to. The curio_servers fixture already passes --auth when it boots
  # its own stack; this is the CURIO_E2E_USE_EXISTING=1 path catching up.
  # CURIO_TESTING is REQUIRED here for the same reason --auth is. The E2E
  # suite seeds users and projects through /api/testing/* and resets the DB
  # between tests through /api/testing/reset-db, and that blueprint refuses
  # with 404 unless the server is BOTH a dev env and a declared test rig
  # (backend/app/testing/routes.py). backend/tests/conftest.py sets the flag
  # for the pytest process, but this server is a child of THIS script, so
  # without it every E2E test errors in its autouse fixture on a bare 404.
  # It also puts the server on the test DB under .curio/test/, which is
  # where the suite already looks.
  set -m
  CURIO_NO_OPEN=1 FLASK_USE_RELOADER=0 CURIO_DEV=1 CURIO_TESTING=1 \
  CURIO_LAUNCH_CWD="$REPO_ROOT" \
    python "$REPO_ROOT/curio.py" start --auth --with-examples \
      --backend-port "$BACKEND_PORT" --sandbox-port "$SANDBOX_PORT" \
      --frontend-port "$FRONTEND_PORT" &
  CURIO_PID=$!
  set +m

  wait_for_port "backend"  "$BACKEND_PORT"
  wait_for_port "sandbox"  "$SANDBOX_PORT"
  wait_for_port "frontend" "$FRONTEND_PORT"
  (( PARALLEL > 1 )) && start_extra_shards
else
  trap cleanup EXIT INT TERM
fi

# ---------------------------------------------------------------------------
# 4. Backend unit tests
# ---------------------------------------------------------------------------
if [[ $RUN_BACKEND -eq 1 ]]; then
  echo ""
  echo "==> Running backend unit tests..."
  PYTHONPATH="$REPO_ROOT" python -m pytest \
    "$REPO_ROOT/utk_curio/backend/tests/" -v \
    --ignore="$REPO_ROOT/utk_curio/backend/tests/test_frontend"
  record "Backend unit tests" $?
fi

# ---------------------------------------------------------------------------
# 5. Sandbox unit tests
# ---------------------------------------------------------------------------
if [[ $RUN_SANDBOX -eq 1 ]]; then
  echo ""
  echo "==> Running sandbox unit tests..."
  # pytest, not `unittest discover`. Discover only collects
  # unittest.TestCase subclasses, so every pytest-style test in this
  # directory (module-level `def test_*` using fixtures) was silently not
  # running: 211 tests collected against 271 under pytest. That quietly
  # excluded the whole test_isolation_linux.py suite, which exists
  # precisely to be run here on Linux, plus test_isolation_staging.py and
  # test_json_artifact_writer.py. pytest runs TestCase classes too, so
  # nothing is lost by switching.
  PYTHONPATH="$REPO_ROOT" python -m pytest "$REPO_ROOT/utk_curio/sandbox/tests" -v
  record "Sandbox unit tests" $?
fi

# ---------------------------------------------------------------------------
# 6. Jest frontend unit tests
# ---------------------------------------------------------------------------
if [[ $RUN_JEST -eq 1 ]]; then
  echo ""
  echo "==> Running Jest frontend unit tests..."
  (cd "$REPO_ROOT/utk_curio/frontend/urban-workflows" && npm test -- --watchAll=false)
  record "Jest frontend unit tests" $?
fi

# ---------------------------------------------------------------------------
# 7. E2E tests (Playwright on host, pointing at the running services)
# ---------------------------------------------------------------------------
if [[ $RUN_E2E -eq 1 ]]; then
  echo ""
  echo "==> Installing Playwright browser..."
  python -m playwright install chromium
  die "playwright install chromium" $?

  PYTEST_ARGS="-v"
  [[ $HEADED -eq 1 ]]    && PYTEST_ARGS="$PYTEST_ARGS --headed"
  # One xdist worker per backend+sandbox pair; loadgroup keeps each workflow's
  # four class-scoped tests (and each other file) on one worker.
  (( PARALLEL > 1 ))     && PYTEST_ARGS="$PYTEST_ARGS -n $PARALLEL --dist loadgroup"
  [[ $VIDEOS -eq 1 ]]    && PYTEST_ARGS="$PYTEST_ARGS --videos"
  [[ $EXAMPLES -eq 1 ]]  && PYTEST_ARGS="$PYTEST_ARGS --with-examples"
  [[ -n "$ALLURE_DIR" ]] && PYTEST_ARGS="$PYTEST_ARGS --alluredir=$ALLURE_DIR"

  E2E_ENV="PYTHONUNBUFFERED=1 CURIO_E2E_USE_EXISTING=1 PYTHONPATH=$REPO_ROOT"
  # Pass the isolation opt-in through to the e2e stack (see the
  # CURIO_E2E_ISOLATION hook in tests/test_frontend/fixtures.py).
  [[ -n "${CURIO_E2E_ISOLATION:-}" ]] && E2E_ENV="$E2E_ENV CURIO_E2E_ISOLATION=$CURIO_E2E_ISOLATION"
  [[ -n "${CURIO_E2E_EXEC_USER:-}" ]] && E2E_ENV="$E2E_ENV CURIO_E2E_EXEC_USER=$CURIO_E2E_EXEC_USER"
  [[ -n "$E2E_WORKFLOWS" ]] && E2E_ENV="$E2E_ENV CURIO_E2E_WORKFLOWS=$E2E_WORKFLOWS"

  echo ""
  echo "==> Running E2E tests..."
  cd "$REPO_ROOT/utk_curio/backend"
  die "cd to utk_curio/backend" $?
  # CURIO_E2E_TARGETS narrows the run to specific files (smoke runs); default is the suite.
  env $E2E_ENV python -m pytest ${CURIO_E2E_TARGETS:-tests/test_frontend/} $PYTEST_ARGS
  record "E2E tests" $?
fi

exit $OVERALL
