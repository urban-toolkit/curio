#!/usr/bin/env bash
# Run one CI test command CURIO_CI_REPEAT times (the Full stack build's
# `repeat` dispatch input; once when unset), every run even after one fails,
# and fail if any run failed. Used to find flaky tests: the CI report lists
# every test that passed in one run and failed in another.
#
# Each "{run}" in the arguments and in PYTEST_ADDOPTS becomes "" in the first
# run, so a single run writes the file names the CI report reads, and
# ".run<k>" in run k after it (e2e.xml, e2e.run2.xml, e2e.run3.xml, ...).
#
#   bash scripts/ci_repeat.sh npm test -- --json --outputFile=ci-report/jest{run}.json
set -uo pipefail

runs="${CURIO_CI_REPEAT:-1}"
if ! [[ "$runs" =~ ^[1-9][0-9]*$ ]]; then
  echo "CURIO_CI_REPEAT must be a positive whole number, not '$runs'" >&2
  exit 2
fi

token='{run}'
addopts="${PYTEST_ADDOPTS-}"
failed=0
for (( run = 1; run <= runs; run++ )); do
  suffix=""
  (( run == 1 )) || suffix=".run$run"
  args=()
  for arg in "$@"; do
    args+=("${arg//"$token"/$suffix}")
  done
  [[ -z "$addopts" ]] || export PYTEST_ADDOPTS="${addopts//"$token"/$suffix}"
  (( runs == 1 )) || echo "::group::Run $run of $runs"
  "${args[@]}" || { failed=$((failed + 1)); echo "Run $run of $runs failed."; }
  (( runs == 1 )) || echo "::endgroup::"
done

if (( failed > 0 )); then
  (( runs == 1 )) || echo "::error::$failed of $runs runs failed"
  exit 1
fi
