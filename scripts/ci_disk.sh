#!/usr/bin/env bash
# Disk room for a CI job: how much is free, and on a GitHub-hosted runner, more
# of it.
#
#   bash scripts/ci_disk.sh free <when>
#   bash scripts/ci_disk.sh drop-tools
#   bash scripts/ci_disk.sh wait-tools
#
# free prints the room left on the file systems of Docker's data root, where
# the CI image is pulled or built, and of the job's workspace,
# under "Free disk <when>:". start-stack prints it before the pull, stop-stack
# at the job's end with the stack still up, and the image cleanup after it, so
# every job's log says how close it came to a full disk. An arcade runner's
# data root is on the disk all 44 share.
#
# drop-tools removes, on a GitHub-hosted runner only, the toolchains its image
# comes with that no CI job uses (TOOLS), for room for the image: GitHub
# promises 14 GB of disk on a standard runner, and a job holds the image plus
# image-env's copy of its packages. It prints the free disk, then runs
# the removal in the background, so the pull or build does not wait for it.
# Kept: the Pythons and Nodes setup-python and setup-node pick from
# (opt/hostedtoolcache/Python and node), and Google Chrome, which the e2e
# suite launches by its path (utk_curio/backend/tests/conftest.py).
# wait-tools waits for that removal, up to five minutes, and prints the free
# disk after it; start-stack runs it once its stack is healthy. On any other
# runner both do nothing.
#
# With RUNNER_ENVIRONMENT, RUNNER_TEMP and GITHUB_WORKSPACE as the runner sets
# them. CURIO_CI_DISK_ROOT puts the toolchains' folders under another root and
# CURIO_CI_DISK_SUDO replaces sudo (tests).
set -u

ROOT="${CURIO_CI_DISK_ROOT:-}"
SUDO="${CURIO_CI_DISK_SUDO-sudo}"
PIDFILE="${RUNNER_TEMP:-/tmp}/curio-drop-tools.pid"
WAIT_S=300

TOOLS=(
  usr/share/dotnet
  usr/local/lib/android
  opt/ghc
  usr/local/.ghcup
  usr/share/swift
  usr/lib/jvm
  usr/local/share/powershell
  opt/az
  opt/microsoft
  opt/hostedtoolcache/CodeQL
  opt/hostedtoolcache/go
  opt/hostedtoolcache/Ruby
  opt/hostedtoolcache/PyPy
)

hosted() { [ "${RUNNER_ENVIRONMENT:-}" = github-hosted ]; }

free() {
  local root
  root=$(docker info --format '{{.DockerRootDir}}' 2> /dev/null || true)
  echo "Free disk $1:"
  df -h --output=target,size,used,avail,pcent ${root:+"$root"} "${GITHUB_WORKSPACE:-$PWD}" 2> /dev/null \
    | awk 'NR == 1 || !seen[$1]++' || true
}

drop_tools() {
  local paths=() tool
  hosted || return 0
  free "before the unused toolchains go"
  for tool in "${TOOLS[@]}"; do
    paths+=("$ROOT/$tool")
  done
  # shellcheck disable=SC2086
  nohup $SUDO rm -rf "${paths[@]}" > /dev/null 2>&1 &
  echo $! > "$PIDFILE"
  echo "removing ${#paths[@]} toolchain folders no CI job uses, in the background"
}

# Whether the removal drop-tools started still runs. Read in /proc, not with
# kill -0: it runs as root, which this user cannot signal. A zombie has ended:
# no process may reap it where PID 1 reaps nothing, as in a container.
removing() {
  [ -d "/proc/$1" ] && ! grep -qs '^State:[[:space:]]*Z' "/proc/$1/status"
}

wait_tools() {
  local pid started
  hosted && [ -f "$PIDFILE" ] || return 0
  pid=$(cat "$PIDFILE")
  started=$(date +%s)
  while removing "$pid" && [ $(( $(date +%s) - started )) -lt "$WAIT_S" ]; do
    sleep 1
  done
  if removing "$pid"; then
    echo "::warning::the unused toolchains were still being removed after ${WAIT_S} s"
  fi
  rm -f "$PIDFILE"
  free "after the unused toolchains went"
}

case "${1:-}" in
  free) free "${2:?when}" ;;
  drop-tools) drop_tools ;;
  wait-tools) wait_tools ;;
  *) echo "usage: $0 free <when> | drop-tools | wait-tools" >&2; exit 2 ;;
esac
