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
#   --use-existing      Skip start/stop; use already-running Curio servers
#   --headed            Open a visible browser window during E2E tests
#   --workflows A,B     Run only the named workflow files (e.g. Vega.json,UTK.json)
#   --e2e-only          Skip unit tests; run only the E2E suite
#   --unit-only         Skip E2E tests; run only backend, sandbox, and frontend unit tests

set -uo pipefail

USE_EXISTING=0
HEADED=0
E2E_WORKFLOWS=""
E2E_ONLY=0
UNIT_ONLY=0

while [[ $# -gt 0 ]]; do
  case $1 in
    --use-existing) USE_EXISTING=1; shift ;;
    --headed)       HEADED=1;       shift ;;
    --workflows)    E2E_WORKFLOWS="$2"; shift 2 ;;
    --e2e-only)     E2E_ONLY=1;     shift ;;
    --unit-only)    UNIT_ONLY=1;    shift ;;
    --help|-h)
      sed -n '2,16p' "$0"
      exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CURIO_PID=""

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
# 1. Clean all build artifacts and runtime data
# ---------------------------------------------------------------------------
bash "$REPO_ROOT/scripts/clean.sh"

# ---------------------------------------------------------------------------
# 2. Install dependencies (needed by both unit tests and E2E)
# ---------------------------------------------------------------------------
echo "==> Installing Python dependencies..."
pip install -r "$REPO_ROOT/requirements.txt" -q

# ---------------------------------------------------------------------------
# 3. Start Curio services (backend :5002, sandbox :2000, frontend :8080)
# ---------------------------------------------------------------------------
if [[ $USE_EXISTING -eq 0 ]]; then
  echo "==> Starting Curio services..."
  trap cleanup EXIT INT TERM
  CURIO_NO_OPEN=1 python "$REPO_ROOT/curio.py" start &
  CURIO_PID=$!

  wait_for_port "backend"  5002
  wait_for_port "sandbox"  2000
  wait_for_port "frontend" 8080
else
  trap cleanup EXIT INT TERM
fi

# ---------------------------------------------------------------------------
# 4. Backend and sandbox unit tests
# ---------------------------------------------------------------------------
if [[ $E2E_ONLY -eq 0 ]]; then
  echo ""
  echo "==> Running backend unit tests..."
  PYTHONPATH="$REPO_ROOT" python -m pytest \
    "$REPO_ROOT/utk_curio/backend/tests/" -v \
    --ignore="$REPO_ROOT/utk_curio/backend/tests/test_frontend"
  record "Backend unit tests" $?

  echo ""
  echo "==> Running sandbox unit tests..."
  PYTHONPATH="$REPO_ROOT" python -m unittest discover \
    -s "$REPO_ROOT/utk_curio/sandbox/tests" -t "$REPO_ROOT" -p "test_*.py" -v
  record "Sandbox unit tests" $?

  echo ""
  echo "==> Running Jest frontend unit tests..."
  (cd "$REPO_ROOT/utk_curio/frontend/urban-workflows" && npm test -- --watchAll=false)
  record "Jest frontend unit tests" $?
fi

# ---------------------------------------------------------------------------
# 5. E2E tests (Playwright on host, pointing at the running services)
# ---------------------------------------------------------------------------
if [[ $UNIT_ONLY -eq 0 ]]; then
  echo ""
  echo "==> Installing Playwright browser..."
  python -m playwright install chromium

  PYTEST_ARGS="-v"
  [[ $HEADED -eq 1 ]] && PYTEST_ARGS="$PYTEST_ARGS --headed"

  E2E_ENV="PYTHONUNBUFFERED=1 CURIO_E2E_USE_EXISTING=1 PYTHONPATH=$REPO_ROOT"
  [[ -n "$E2E_WORKFLOWS" ]] && E2E_ENV="$E2E_ENV CURIO_E2E_WORKFLOWS=$E2E_WORKFLOWS"

  echo ""
  echo "==> Running E2E tests..."
  cd "$REPO_ROOT/utk_curio/backend"
  env $E2E_ENV python -m pytest tests/test_frontend/ $PYTEST_ARGS
  record "E2E tests" $?
fi

exit $OVERALL
