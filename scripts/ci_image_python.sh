#!/usr/bin/env bash
# The CI image's Python packages for a pytest that runs on the runner, as
# .github/actions/image-env gives them to a job: a virtual environment of the
# runner's Python 3.12 whose site-packages is the image's, with its bin/ first
# on the job's PATH.
#
#   bash scripts/ci_image_python.sh take <image>
#   bash scripts/ci_image_python.sh release
#
# On an arcade runner the site-packages folder is the image's own, mounted
# read-only in place. A helper container from the image binds its
# /usr/local/lib/python3.12/site-packages onto the virtual environment's empty
# site-packages folder, and the bind reaches the runner because the runner's
# entrypoint makes its root mount rshared (uic-evl/evl-github-runners). The
# paths are a real folder's, so Python's and Node's realpath (Playwright's
# driver) stay inside it. Copying the folder instead wrote 9.4 GB per job, in
# 62,000 files, and a run starts up to 15 such jobs on arcade at once: about
# 140 GB on the disk all its runners share, within two minutes, which held
# every disk write on arcade for up to 40 s (11-07, run 42344025435). Each
# runner already holds the image, so the mount writes nothing and takes no
# disk.
#
# Elsewhere (GitHub-hosted runners, utk-gpu, the utk-desktop runners) the
# packages are copied as before, and so they are on an arcade runner whose
# mount does not come up, with a warning that says why. A mode line,
# `image-env: in place` or `image-env: copy (<why>)`, says which a job got.
#
# release lets go of the mounts: each helper unmounts its bind, which leaves
# the runner the same way it came, then goes. A helper that was killed while
# mounted leaves its bind behind, and a privileged container unmounts it in
# the runner's mount namespace (PID 1's); only binds under the folder this
# script mounts in are touched. stop-stack runs it before the image cleanup,
# since a helper holds its image, and take runs it first. On a runner that is
# not an arcade one it does nothing.
#
# With RUNNER_NAME, RUNNER_TEMP, HOME and GITHUB_PATH as the runner sets them.
# CURIO_CI_MOUNTINFO names the mount table to read (tests).
set -euo pipefail

SITE_IN_IMAGE=/usr/local/lib/python3.12/site-packages
LABEL=curio-ci.image-python
MOUNTS="$HOME/curio-image-python"
MOUNTINFO="${CURIO_CI_MOUNTINFO:-/proc/self/mountinfo}"

arcade() { [[ "${RUNNER_NAME:-}" == arcade-* ]]; }

now_ms() { date +%s%3N; }

# Seconds since a now_ms, to a tenth.
seconds_since() {
  local ms=$(( $(now_ms) - $1 ))
  echo "$(( ms / 1000 )).$(( ms % 1000 / 100 ))"
}

# Bytes written to disk by an arcade runner's container, the cgroup that holds
# the runner, its jobs and its Docker daemon. Elsewhere the cgroup is a host's,
# shared with whatever else runs there, so nothing is read.
written() {
  arcade || return 0
  awk '{ for (i = 2; i <= NF; i++) if ($i ~ /^wbytes=/) { split($i, kv, "="); sum += kv[2] } }
       END { printf "%d\n", sum }' /sys/fs/cgroup/io.stat 2> /dev/null || true
}

# ", and the runner wrote N bytes to disk meanwhile", when both reads worked.
wrote_since() {
  local now
  now=$(written)
  if [ -n "$1" ] && [ -n "$now" ]; then
    echo ", and the runner wrote $(( now - $1 )) bytes to disk meanwhile"
  fi
}

# The binds left under $MOUNTS, from the mount table's fifth field.
left_mounted() {
  awk -v root="$MOUNTS/" 'index($5, root) == 1 { print $5 }' "$MOUNTINFO" 2> /dev/null || true
}

release() {
  arcade || return 0
  local cid mnt
  for cid in $(docker ps -q --filter "label=$LABEL"); do
    docker exec "$cid" umount -l /mnt/site > /dev/null 2>&1 || true
  done
  docker ps -aq --filter "label=$LABEL" | xargs -r docker rm -f > /dev/null 2>&1 || true
  for mnt in $(left_mounted); do
    echo "unmounting $mnt, which a helper left behind"
    docker run --rm --privileged --pid=host --network none alpine \
      nsenter -t 1 -m -- umount -l "$mnt" || true
  done
  if [ -n "$(left_mounted)" ]; then
    echo "::warning::image-env: still mounted under $MOUNTS: $(left_mounted | tr '\n' ' ')"
  else
    rm -rf "$MOUNTS" || true
  fi
}

# The image's site-packages, read-only in place, in a virtual environment
# under $MOUNTS. Sets WHY and returns 1 when the mount does not serve.
in_place() {
  local image=$1 venv site
  venv="$MOUNTS/${GITHUB_RUN_ID:-run}-${GITHUB_RUN_ATTEMPT:-1}-$$"
  mkdir -p "$MOUNTS"
  python -m venv --without-pip "$venv"
  site="$venv/lib/python3.12/site-packages"
  if ! docker run -d --rm --privileged --network none --log-driver none --label "$LABEL=$site" \
      --mount "type=bind,source=$site,target=/mnt/site,bind-propagation=rshared" \
      --entrypoint bash "$image" \
      -c "mount --bind -o ro $SITE_IN_IMAGE /mnt/site && exec sleep infinity" > /dev/null; then
    WHY="its helper container did not start"
    return 1
  fi
  for _ in $(seq 1 100); do
    mountpoint -q "$site" && break
    sleep 0.1
  done
  if ! mountpoint -q "$site"; then
    WHY="no mount reached the runner within 10 s"
    return 1
  fi
  if ! "$venv/bin/python" -c 'import playwright, pytest'; then
    WHY="playwright and pytest do not import from the mount"
    return 1
  fi
  echo "$venv/bin" >> "$GITHUB_PATH"
}

# The way every runner took them before: the image's site-packages copied into
# a virtual environment under RUNNER_TEMP.
copy() {
  local image=$1 venv site started
  started=$(date +%s)
  venv="$RUNNER_TEMP/curio-image-python"
  rm -rf "$venv"
  python -m venv --without-pip "$venv"
  site="$venv/lib/python3.12/site-packages"
  # docker cp copies a folder into one that already exists, one level down.
  rmdir "$site"
  # Not local: when the copy fails, the trap runs after this function is gone.
  COPY_CONTAINER="$(docker create "$image")"
  trap 'docker rm -f "${COPY_CONTAINER:-}" > /dev/null 2>&1 || true' EXIT
  docker cp "$COPY_CONTAINER:$SITE_IN_IMAGE" "$site"
  docker rm -f "$COPY_CONTAINER" > /dev/null 2>&1 || true
  trap - EXIT
  "$venv/bin/python" -c 'import playwright, pytest'
  echo "$venv/bin" >> "$GITHUB_PATH"
  echo "Copied $(du -sh "$site" | cut -f1) of packages in $(( $(date +%s) - started )) s"
}

take() {
  local image=$1 started before why
  started=$(now_ms)
  before=$(written)
  WHY=""
  if arcade; then
    release
    if in_place "$image"; then
      echo "image-env: in place: the image's site-packages, read-only, nothing copied," \
        "in $(seconds_since "$started") s$(wrote_since "$before")"
      return 0
    fi
    echo "::warning::image-env: the image's packages could not be used in place ($WHY), so they are copied"
    release
    why="in place failed: $WHY"
  else
    why="not an arcade runner"
  fi
  copy "$image"
  echo "image-env: copy ($why), in $(seconds_since "$started") s$(wrote_since "$before")"
}

case "${1:-}" in
  take) take "${2:?the CI image}" ;;
  release) release ;;
  *) echo "usage: $0 take <image> | release" >&2; exit 2 ;;
esac
