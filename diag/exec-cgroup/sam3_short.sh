#!/usr/bin/env bash
# SAM 3's Track Objects to the end, on shorter parts of the walk, in a node
# cgroup at dev's 24576 MB (a diagnostic, after run 42708730576 found that 300 s
# at one frame every 0.5 s outgrows utk's 96 GB GPU). Same container shape as
# sam3_host.sh; removes its container, image tag and download at the end.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
IMAGE="diag-cgroup-sam3:${GITHUB_RUN_ID:-local}"
NAME="diag-cgroup-sam3-${GITHUB_RUN_ID:-local}"
WALK_URL="https://data.urbantk.org/sideseeing/chicago/west-loop/2026-10-26-16-03-17-016/video.mp4"
WALK_DIR="${RUNNER_TEMP:-/tmp}/diag-cgroup-walk"

section() { echo; echo "===== $*"; }
run() { echo "+ $*"; "$@"; echo "exit $?"; }
cleanup() {
  docker rm -f "$NAME" > /dev/null 2>&1
  docker image rm "$IMAGE" > /dev/null 2>&1
  rm -rf "$WALK_DIR"
}
trap cleanup EXIT

section "build CI's image with CUDA torch (CURIO_CI_SETUP=1, as test-gpu builds it)"
docker build -q --build-arg CURIO_CI_SETUP=1 -t "$IMAGE" "$ROOT" > /dev/null 2>&1
docker image inspect "$IMAGE" > /dev/null 2>&1 || { echo "no image"; exit 1; }

section "the walk"
mkdir -p "$WALK_DIR"
run curl -fsS -o "$WALK_DIR/video.mp4" "$WALK_URL"
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv

run docker run -d --name "$NAME" --init --gpus all -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
  --security-opt writable-cgroups=true --cgroupns private \
  -v "$HERE:/diag:ro" \
  -v "$ROOT/packages/model.curio.sam3@1/sources:/sam3-sources:ro" -e DIAG_PACKAGE_SOURCES=/sam3-sources \
  -v /srv/curio-model-weights:/model-weights:ro -v "$WALK_DIR:/video:ro" \
  --entrypoint sleep "$IMAGE" infinity
docker inspect "$NAME" > /dev/null 2>&1 || exit 1
run docker exec "$NAME" python /diag/cgroup_lab.py setup

for seconds in 60 150; do
  section "SAM 3: 0 to $seconds s of the walk, one frame every 0.5 s, memory.max 24576 MB"
  run timeout 1500 docker exec -e DIAG_TO_SECONDS="$seconds" "$NAME" python /diag/sam3_measure.py "to-$seconds-s" 24576
done
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv
