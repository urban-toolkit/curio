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
# CURIO_CI_FRESH_STACK names the job's compose project. Every run after the
# first then starts on a recreated stack, as a run of its own would: some
# tests cannot run twice on one server session (test_library_install_integration
# leaves its library warm in the sandbox's sys.modules).
#
#   bash scripts/ci_repeat.sh npm test -- --json --outputFile=ci-report/jest{run}.json
set -uo pipefail

runs="${CURIO_CI_REPEAT:-1}"
if ! [[ "$runs" =~ ^[1-9][0-9]*$ ]]; then
  echo "CURIO_CI_REPEAT must be a positive whole number, not '$runs'" >&2
  exit 2
fi

# Recreate the stack from its image and wait for the image's health check, as
# start-stack does at the start of the job.
fresh_stack() {
  local project=$1 waited cid health
  echo "Recreating $project for this run"
  docker compose -p "$project" up -d --force-recreate --no-build || return 1
  for (( waited = 0; waited < 420; waited += 5 )); do
    cid="$(docker compose -p "$project" ps -q curio | head -n1)"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$cid" 2>/dev/null)"
    [[ "$health" == healthy ]] && { echo "$project is healthy."; return 0; }
    sleep 5
  done
  echo "::error::$project did not become healthy again in 420s" >&2
  docker compose -p "$project" logs --no-color --tail=200 curio || true
  return 1
}

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
  if (( run > 1 )) && [[ -n "${CURIO_CI_FRESH_STACK:-}" ]] && ! fresh_stack "$CURIO_CI_FRESH_STACK"; then
    failed=$((failed + 1))
    echo "Run $run of $runs did not start: the stack did not come back."
  else
    "${args[@]}" || { failed=$((failed + 1)); echo "Run $run of $runs failed."; }
  fi
  (( runs == 1 )) || echo "::endgroup::"
done

if (( failed > 0 )); then
  (( runs == 1 )) || echo "::error::$failed of $runs runs failed"
  exit 1
fi
