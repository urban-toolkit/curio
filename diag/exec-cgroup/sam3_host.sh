#!/usr/bin/env bash
# SAM 3's Track Objects in a node cgroup on utk, for its real resident peak (a
# diagnostic). Builds CI's image with CUDA torch as test-gpu does (Docker's
# build cache), reads the fetched weights read-only where dev and stable keep
# them, and tracks 300 s of a SideSeeing walk with the shipped node's settings.
# Removes its container, image and download at the end; prunes nothing.
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

section "the weights dev and stable read"
ls -la /srv/curio-model-weights/ 2>&1 | head -20
find /srv/curio-model-weights -maxdepth 3 -name '*.safetensors' -exec ls -la {} \; 2>&1 | head -10

section "build CI's image with CUDA torch (CURIO_CI_SETUP=1, as test-gpu builds it)"
started=$(date +%s)
BUILD_LOG="${RUNNER_TEMP:-/tmp}/diag-cgroup-build.log"
docker build --progress=plain --build-arg CURIO_CI_SETUP=1 -t "$IMAGE" "$ROOT" > "$BUILD_LOG" 2>&1
echo "build exit $?, took $(( $(date +%s) - started )) s; the layers it ran (not cached):"
grep -E '^#[0-9]+ \[' "$BUILD_LOG" | grep -v CACHED | sort -u | head -40
grep -c CACHED "$BUILD_LOG" | sed 's/^/cached steps: /'
tail -n 15 "$BUILD_LOG"
rm -f "$BUILD_LOG"
docker image inspect "$IMAGE" > /dev/null 2>&1 || exit 1

section "the walk"
mkdir -p "$WALK_DIR"
started=$(date +%s)
run curl -fsS -o "$WALK_DIR/video.mp4" "$WALK_URL"
echo "download took $(( $(date +%s) - started )) s, $(stat -c %s "$WALK_DIR/video.mp4") bytes"

section "the GPU before"
nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv

section "a container with writable cgroups, the GPU, the weights read-only and the walk"
run docker run -d --name "$NAME" --init --gpus all -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
  --security-opt writable-cgroups=true --cgroupns private \
  -v "$HERE:/diag:ro" \
  -v "$ROOT/packages/model.curio.sam3@1/sources:/sam3-sources:ro" -e DIAG_PACKAGE_SOURCES=/sam3-sources \
  -v /srv/curio-model-weights:/model-weights:ro -v "$WALK_DIR:/video:ro" \
  --entrypoint sleep "$IMAGE" infinity
docker inspect "$NAME" > /dev/null 2>&1 || exit 1
run docker exec "$NAME" python /diag/cgroup_lab.py facts
run docker exec "$NAME" python /diag/cgroup_lab.py setup
run docker exec "$NAME" python -c "import torch, transformers, av; print('torch', torch.__version__, 'cuda', torch.version.cuda, 'transformers', transformers.__version__, 'av', av.__version__)"
run docker exec "$NAME" python /diag/cgroup_lab.py gpu --gib 20

section "torch in a node capped at 24576 MB: 20 GiB on the GPU"
run docker exec "$NAME" python /diag/torch20.py

section "SAM 3: cold (the walk and the weights out of the page cache), no memory.max"
run timeout 1800 docker exec "$NAME" python /diag/sam3_measure.py cold-nocap 0 --cold
section "SAM 3: warm, memory.max 24576 MB (dev's --exec-memory-mb)"
run timeout 1800 docker exec "$NAME" python /diag/sam3_measure.py warm-24576 24576
section "SAM 3: warm, memory.max 8192 MB"
run timeout 1800 docker exec "$NAME" python /diag/sam3_measure.py warm-8192 8192
section "SAM 3: today's cap, RLIMIT_AS at what the zygote's imports map plus 24576 MB, no memory.max"
run timeout 900 docker exec "$NAME" python /diag/sam3_measure.py rlimit-as-24576 0 --rlimit-as-mb 24576

section "the GPU after"
nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv
echo "docker stats: $(docker stats --no-stream --format '{{.MemUsage}} {{.PIDs}} pids' "$NAME" 2>&1)"
