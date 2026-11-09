#!/usr/bin/env bash
# tmp/sharded-backend: the stress job's two stages at several backend process
# counts in turn, each on a fresh stack (an empty .curio), with the standard
# stages: 10 canvases of 10 users, then the same with every member's agent at
# work on the scripted model.
#
#   bash scripts/ci_stress_shards.sh 1 4 8
#
# 1 goes through nginx too (CURIO_BACKEND_ROUTER), as the others do. Run from
# the job's workspace with its environment (COMPOSE_FILE and the port
# variables) and the image's Python on PATH (image-env). Writes, for each K:
# stress-canvas.k<K>/ and stress-agents.k<K>/ (the reports),
# stress-messages.k<K>.txt (the stack's messages.log), stress-container-logs.k<K>.txt,
# stress-nginx.k<K>.conf, docker-stats.k<K>.log, and a line in stress-boot.txt.
# A red stage does not stop the next K; the script exits 1 at the end if any
# stage or start failed. The last stack is left up for the job's later steps.
set -uo pipefail

project=curio-ci-stress
backend="http://localhost:5072"
work="${GITHUB_WORKSPACE:-$PWD}"
last="${*: -1}"
status=0

for K in "$@"; do
  echo "::group::$K backend process(es): fresh stack"
  # The stack's .curio is root's alone once the execution user hardens it.
  docker run --rm -v "$work:/w" -w /w alpine rm -rf .curio || true
  : > "$work/docker-stats.log"
  export CURIO_BACKEND_PROCESSES="$K"
  if [ "$K" = 1 ]; then export CURIO_BACKEND_ROUTER=1; else export CURIO_BACKEND_ROUTER=; fi
  started=$(date +%s)
  healthy=0
  if docker compose -p "$project" up -d; then
    deadline=$((started + 900))
    while [ "$(date +%s)" -lt "$deadline" ]; do
      if curl -sf -o /dev/null --max-time 5 "$backend/health"; then
        healthy=1
        break
      fi
      cid="$(docker compose -p "$project" ps -a -q curio | head -n1 || true)"
      state="$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || true)"
      if [ "$state" = "exited" ]; then
        echo "the stack with $K backend process(es) exited during startup"
        break
      fi
      sleep 2
    done
  fi
  boot=$(( $(date +%s) - started ))
  cid="$(docker compose -p "$project" ps -q curio | head -n1 || true)"
  echo "::endgroup::"

  if [ "$healthy" = 1 ]; then
    echo "K=$K: the stack answered /health $boot s after compose up"
    echo "::group::$K backend process(es): 10 canvases of 10 users"
    python -m utk_curio.backend.tests.stress \
      --backend "$backend" \
      --tiers 100 --room-size 10 --shared-canvas \
      --backend-processes "$K" \
      --out "$work/stress-canvas.k$K" \
      --stats-log "$work/docker-stats.log" \
      --probe "docker exec $cid python" || status=1
    echo "::endgroup::"
    echo "::group::$K backend process(es): 10 canvases of 10 users with agents"
    python -m utk_curio.backend.tests.stress \
      --backend "$backend" \
      --tiers 100 --room-size 10 --shared-canvas --agents \
      --backend-processes "$K" \
      --out "$work/stress-agents.k$K" \
      --stats-log "$work/docker-stats.log" \
      --probe "docker exec $cid python" || status=1
    echo "::endgroup::"
  else
    echo "::error::the stack with $K backend process(es) never answered /health ($boot s)"
    docker compose -p "$project" logs --no-color --tail=300 curio || true
    status=1
  fi

  docker compose -p "$project" logs --no-color --tail=50000 > "$work/stress-container-logs.k$K.txt" 2>&1 || true
  docker run --rm -v "$work:/w" -w /w alpine sh -c 'cat .curio/messages.log 2>/dev/null' \
    > "$work/stress-messages.k$K.txt" 2>&1 || true
  docker run --rm -v "$work:/w" -w /w alpine sh -c 'cat .curio/nginx/nginx.conf 2>/dev/null' \
    > "$work/stress-nginx.k$K.conf" 2>&1 || true
  cp "$work/docker-stats.log" "$work/docker-stats.k$K.log" 2>/dev/null || true
  {
    echo "K=$K: healthy=$healthy, $boot s from compose up to /health"
    grep -h "\[backend-group\]" "$work/stress-messages.k$K.txt" || true
  } >> "$work/stress-boot.txt"
  if [ "$K" != "$last" ]; then
    docker compose -p "$project" down --timeout 60 || true
  fi
done

cat "$work/stress-boot.txt" || true
exit "$status"
