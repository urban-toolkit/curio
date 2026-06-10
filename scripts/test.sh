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
#   --headed            Open a visible browser window during E2E tests
#   --workflows A,B     Run only the named workflow files (e.g. Vega.json,Regression.json)
#   --backend-only      Run only backend unit tests
#   --sandbox-only      Run only sandbox unit tests
#   --jest-only         Run only Jest frontend unit tests
#   --e2e-only          Run only the E2E suite
#   --unit-only         Run only backend, sandbox, and frontend unit tests (no E2E)
#   --allure-dir DIR    Write Allure results to DIR (passed to E2E pytest)

set -uo pipefail

USE_EXISTING=0
HEADED=0
E2E_WORKFLOWS=""
ALLURE_DIR=""
SUITE="all"   # all | backend | sandbox | jest | e2e | unit

while [[ $# -gt 0 ]]; do
  case $1 in
    --use-existing)  USE_EXISTING=1;       shift ;;
    --headed)        HEADED=1;             shift ;;
    --workflows)     E2E_WORKFLOWS="$2";   shift 2 ;;
    --backend-only)  SUITE="backend";      shift ;;
    --sandbox-only)  SUITE="sandbox";      shift ;;
    --jest-only)     SUITE="jest";         shift ;;
    --e2e-only)      SUITE="e2e";          shift ;;
    --unit-only)     SUITE="unit";         shift ;;
    --allure-dir)    ALLURE_DIR="$2";      shift 2 ;;
    --help|-h)
      sed -n '2,20p' "$0"
      exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CURIO_PID=""

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
      exit 1
    fi
    if python -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('localhost', $port)); s.close()" 2>/dev/null; then
      echo "    $name is ready."
      return
    fi
    sleep 1
  done
  echo "ERROR: $name (port $port) did not start within 240 s" >&2
  exit 1
}

cleanup() {
  if [[ -n "$CURIO_PID" ]]; then
    echo ""
    echo "==> Stopping Curio (pid $CURIO_PID)..."
    kill "$CURIO_PID" 2>/dev/null || true
    wait "$CURIO_PID" 2>/dev/null || true
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
fi

# ---------------------------------------------------------------------------
# 2. Install dependencies (needed by both unit tests and E2E)
# ---------------------------------------------------------------------------
echo "==> Installing Python dependencies..."
pip install -r "$REPO_ROOT/requirements.txt" -q

echo "==> Installing manifest python deps via curio setup..."
PYTHONPATH="$REPO_ROOT" python "$REPO_ROOT/curio.py" setup

if [[ $USE_EXISTING -eq 0 ]]; then
  echo "==> Installing frontend npm dependencies..."
  (cd "$REPO_ROOT/utk_curio/frontend/urban-workflows" && npm install -q)
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
  CURIO_NO_OPEN=1 FLASK_USE_RELOADER=0 CURIO_DEV=1 CURIO_LAUNCH_CWD="$REPO_ROOT" \
    python "$REPO_ROOT/curio.py" start &
  CURIO_PID=$!

  wait_for_port "backend"  5002
  wait_for_port "sandbox"  2000
  wait_for_port "frontend" 8080
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
  PYTHONPATH="$REPO_ROOT" python -m unittest discover \
    -s "$REPO_ROOT/utk_curio/sandbox/tests" -t "$REPO_ROOT" -p "test_*.py" -v
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

  PYTEST_ARGS="-v"
  [[ $HEADED -eq 1 ]]    && PYTEST_ARGS="$PYTEST_ARGS --headed"
  [[ -n "$ALLURE_DIR" ]] && PYTEST_ARGS="$PYTEST_ARGS --alluredir=$ALLURE_DIR"

  E2E_ENV="PYTHONUNBUFFERED=1 CURIO_E2E_USE_EXISTING=1 PYTHONPATH=$REPO_ROOT"
  [[ -n "$E2E_WORKFLOWS" ]] && E2E_ENV="$E2E_ENV CURIO_E2E_WORKFLOWS=$E2E_WORKFLOWS"

  echo ""
  echo "==> Running E2E tests..."
  cd "$REPO_ROOT/utk_curio/backend"
  env $E2E_ENV python -m pytest tests/test_frontend/ $PYTEST_ARGS
  record "E2E tests" $?
fi

exit $OVERALL
