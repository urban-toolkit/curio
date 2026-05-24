#!/usr/bin/env bash
# Kill ghost Curio server processes (backend, sandbox, frontend / vite).
#
# Use this when ``curio start`` falls back to an alternate port (e.g. 8082
# instead of 8080) because a previous run left orphaned listeners — or before
# running the e2e suite, whose server fixture has a tight startup budget that
# is easy to blow when ports first need to be cleared.
#
# Works on Windows (Git Bash / MINGW64) and Unix-like systems.
#
# Usage:
#   ./scripts/kill-curio.sh

set -uo pipefail

# Canonical curio ports + frontends used by the e2e fixture.
PORTS=(5002 2000 8080 5001 5173 3000 8081 8082)

is_windows() {
    case "${OSTYPE:-}" in
        msys|cygwin|win32) return 0 ;;
        *) return 1 ;;
    esac
}

echo "==> Releasing curio ports: ${PORTS[*]}"
for port in "${PORTS[@]}"; do
    if command -v npx >/dev/null 2>&1; then
        npx --yes kill-port "$port" >/dev/null 2>&1 || true
    fi
done

echo "==> Killing curio python / vite / backend / sandbox processes by command line"
if is_windows; then
    powershell -NoProfile -Command "
        Get-CimInstance Win32_Process |
          Where-Object {
              \$_.CommandLine -match 'curio\.py' -or
              \$_.CommandLine -match 'utk_curio.*main' -or
              \$_.CommandLine -match 'backend\.server' -or
              \$_.CommandLine -match 'sandbox\.server' -or
              \$_.CommandLine -match 'vite' -or
              \$_.CommandLine -match 'webpack' -or
              \$_.CommandLine -match 'urban-workflows'
          } |
          ForEach-Object {
              Write-Host (\"  killing PID \" + \$_.ProcessId + \" :: \" + \$_.Name)
              Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue
          }
    " 2>/dev/null || true
else
    pkill -f 'curio\.py'        2>/dev/null || true
    pkill -f 'utk_curio.*main'  2>/dev/null || true
    pkill -f 'backend\.server'  2>/dev/null || true
    pkill -f 'sandbox\.server'  2>/dev/null || true
    pkill -f 'vite'             2>/dev/null || true
    pkill -f 'webpack'          2>/dev/null || true
    pkill -f 'urban-workflows'  2>/dev/null || true
fi

echo "==> Done."
