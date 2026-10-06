#!/usr/bin/env bash
# The compose plumbing shared by every CI job that runs a Curio stack from the
# CI image: the start-stack and stop-stack actions, and the flake hunt's lanes
# (scripts/ci_lanes.py), which start several stacks on one runner. Run it from
# the directory whose compose files and bind mounts (./.curio, ./instance,
# ./datasets) the stack uses; the overlays come from COMPOSE_FILE.
#
#   ci_stack.sh clean PATTERN          remove every stack whose project matches PATTERN (grep -E)
#   ci_stack.sh pull IMAGE PROJECT     pull IMAGE and tag it with the name compose gives PROJECT's image
#   ci_stack.sh up PROJECT             start PROJECT's containers without building
#   ci_stack.sh wait PROJECT SECONDS   wait until PROJECT reports healthy
#   ci_stack.sh down PROJECT           tear PROJECT down
#   ci_stack.sh handback               hand root-owned workspace files back, remove other commits' CI images
set -euo pipefail

usage() {
  sed -n '8,13p' "$0" >&2
  exit 2
}

# A self-hosted runner keeps its Docker daemon between jobs, and a job that
# was cancelled may not have torn its stack down. Left running, compose would
# reuse it under the next job, on a workspace checkout has since wiped. Remove
# every matching stack still there, whatever its project (the daemon is this
# runner's own), by label so no compose file is needed.
clean() {
  local pattern=$1 projects project label
  projects=$(docker ps -a --format '{{.Label "com.docker.compose.project"}}' | grep -E "$pattern" | sort -u || true)
  for project in $projects; do
    echo "removing stack $project"
    label="label=com.docker.compose.project=$project"
    docker ps -aq --filter "$label" | xargs -r docker rm -f
    docker volume ls -q --filter "$label" | xargs -r docker volume rm
    docker network ls -q --filter "$label" | xargs -r docker network rm
  done
}

# Tagged with the name compose gives the service's image, so `up` finds it and
# builds nothing.
pull() {
  local image=$1 project=$2
  docker pull --quiet "$image"
  docker tag "$image" "$project-curio"
}

up() {
  docker compose -p "$1" up -d --no-build
}

# One pass of the health loop, run under `timeout` by wait_healthy.
poll() {
  local project=$1 cid state health
  while true; do
    cid="$(docker compose -p "$project" ps -a -q curio | head -n1 || true)"
    if [[ -z "${cid}" ]]; then sleep 2; continue; fi
    state="$(docker inspect --format "{{.State.Status}}" "${cid}" 2>/dev/null || true)"
    health="$(docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}" "${cid}" 2>/dev/null || true)"
    if [[ "${health}" == "healthy" ]]; then echo "$project is healthy."; break; fi
    if [[ "${health}" == "no-healthcheck" && "${state}" == "running" ]]; then break; fi
    if [[ "${state}" == "exited" ]]; then
      echo "$project exited during startup. Logs:"
      docker compose -p "$project" logs --no-color --tail=200 curio || true
      exit 1
    fi
    sleep 2
  done
}

wait_healthy() {
  local project=$1 wait=$2
  timeout "$wait" bash "$0" _poll "$project" \
    || { echo "::error::$project did not become healthy in ${wait}s" >&2
         docker compose -p "$project" logs --no-color --tail=200 curio || true
         exit 1; }
}

down() {
  local project=$1
  docker compose -p "$project" down -v --remove-orphans || true
  docker ps -aq --filter "label=com.docker.compose.project=$project" | xargs -r docker rm -f
}

# The containers run as root and write into the bind-mounted checkout, which
# the runner user cannot clean otherwise. Every commit pulls a new image of
# several GB, and the daemon is this runner's own, so the images of other
# commits go; `docker image rm` without -f skips any still in use.
handback() {
  docker run --rm -v "$PWD:/w" -w /w alpine chown -R "$(id -u):$(id -g)" /w 2>/dev/null || true
  local repo="ghcr.io/${GITHUB_REPOSITORY,,}-ci"
  docker image ls "$repo" --format '{{.Repository}}:{{.Tag}}' \
    | { grep -v ":${GITHUB_SHA}\$" || true; } \
    | xargs -r docker image rm > /dev/null 2>&1 || true
  docker image prune -f > /dev/null 2>&1 || true
}

command=${1:-}
shift || true
case "$command" in
  clean)    [[ $# -eq 1 ]] || usage; clean "$1" ;;
  pull)     [[ $# -eq 2 ]] || usage; pull "$1" "$2" ;;
  up)       [[ $# -eq 1 ]] || usage; up "$1" ;;
  wait)     [[ $# -eq 2 ]] || usage; wait_healthy "$1" "$2" ;;
  _poll)    [[ $# -eq 1 ]] || usage; poll "$1" ;;
  down)     [[ $# -eq 1 ]] || usage; down "$1" ;;
  handback) [[ $# -eq 0 ]] || usage; handback ;;
  *)        usage ;;
esac
