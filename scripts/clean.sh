#!/usr/bin/env bash
# Remove all build artifacts and runtime data.
#
# Usage:
#   ./scripts/clean.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Cleaning build artifacts..."

rm -rf "$REPO_ROOT/.curio"
rm -rf "$REPO_ROOT/utk_curio/frontend/urban-workflows/node_modules"
rm -rf "$REPO_ROOT/utk_curio/frontend/urban-workflows/dist"
rm -rf "$REPO_ROOT/utk_curio/frontend/urban-workflows/build"
# Never into ./bucket-mounts: a bucket the mount service has mounted there is
# the source's, and a walk would list all of it.
find "$REPO_ROOT" -path "$REPO_ROOT/bucket-mounts" -prune -o -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$REPO_ROOT" -path "$REPO_ROOT/bucket-mounts" -prune -o -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
rm -rf "$REPO_ROOT/dist" "$REPO_ROOT/build" "$REPO_ROOT/htmlcov"

echo "==> Clean complete."
