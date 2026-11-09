#!/usr/bin/env bash
# What a container on this runner's Docker may do with cgroups (a diagnostic).
# Every write happens inside a throwaway container's own cgroup namespace
# (cgroup_lab.py refuses otherwise); every container this makes is removed.
#   PROBE_NAME   a short name for this host
#   PROBE_GPU    1 to hand the containers the GPU, as deploy.yml and test-gpu do
#   PROBE_GPU_GIB  device memory the GPU check asks for (at most half of what is free)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
IMAGE=python:3.12-slim
TAG="diag-cgroup-${GITHUB_RUN_ID:-local}-${PROBE_NAME:-host}"
GPU_ARGS=()
if [ "${PROBE_GPU:-0}" = 1 ]; then
  GPU_ARGS=(--gpus all -e NVIDIA_DRIVER_CAPABILITIES=compute,utility)
fi

section() { echo; echo "===== $*"; }
run() { echo "+ $*"; "$@"; echo "exit $?"; }

section "host $PROBE_NAME"
uname -a
grep PRETTY_NAME /etc/os-release
id
echo "cpus $(nproc)"
grep -E 'MemTotal|MemAvailable|SwapTotal|SwapFree' /proc/meminfo
stat -fc 'cgroup fs: %T' /sys/fs/cgroup
grep -E ' /sys/fs/cgroup ' /proc/self/mountinfo
echo "this shell's cgroup: $(cat /proc/self/cgroup)"
echo "its cgroup's controllers: $(cat /sys/fs/cgroup/cgroup.controllers 2>&1)"
echo "cgroupns inode $(stat -Lc %i /proc/self/ns/cgroup), pidns inode $(stat -Lc %i /proc/self/ns/pid) (the host's are 4026531835 and 4026531836)"
systemctl --version 2>/dev/null | head -1 || echo "no systemctl"
echo "AppArmor enabled: $(cat /sys/module/apparmor/parameters/enabled 2>&1)"
docker version --format 'docker server {{.Server.Version}} (API {{.Server.APIVersion}}), client {{.Client.Version}}'
docker version --format '{{range .Server.Components}}{{.Name}} {{.Version}}; {{end}}'
docker info --format 'cgroup driver {{.CgroupDriver}}, cgroup v{{.CgroupVersion}}, security {{json .SecurityOptions}}, default runtime {{.DefaultRuntime}}, kernel {{.KernelVersion}}, {{.OperatingSystem}}, {{.NCPU}} CPUs, {{.MemTotal}} bytes'
docker compose version
cat /etc/docker/daemon.json 2>/dev/null || echo "no readable /etc/docker/daemon.json"
if [ "${PROBE_GPU:-0}" = 1 ]; then
  nvidia-smi -L
  nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version --format=csv
fi

run docker pull -q "$IMAGE"

section "1. a container as deploy.yml starts it: --init, Docker's seccomp and AppArmor, no capability added"
run docker run --rm --init "${GPU_ARGS[@]}" -v "$HERE:/diag:ro" "$IMAGE" python3 /diag/cgroup_lab.py facts --try-write
cid="$(docker create --init "${GPU_ARGS[@]}" "$IMAGE" true)"
docker inspect -f 'what the daemon gave it: cgroupns {{.HostConfig.CgroupnsMode}}, security_opt {{json .HostConfig.SecurityOpt}}, AppArmor {{.AppArmorProfile}}, privileged {{.HostConfig.Privileged}}' "$cid"
docker rm -f "$cid" > /dev/null

probe_writable() {
  # $1 container name, then extra docker run options
  local name="$1"
  shift
  docker rm -f "$name" > /dev/null 2>&1
  run docker run -d --name "$name" --init "${GPU_ARGS[@]}" --security-opt writable-cgroups=true --cgroupns private "$@" \
    -v "$HERE:/diag:ro" "$IMAGE" sleep infinity
  if ! docker inspect "$name" > /dev/null 2>&1; then
    echo "no container: the daemon refused the options above"
    return
  fi
  docker inspect -f 'what the daemon gave it: cgroupns {{.HostConfig.CgroupnsMode}}, security_opt {{json .HostConfig.SecurityOpt}}, AppArmor {{.AppArmorProfile}}, memory {{.HostConfig.Memory}}, pids {{.HostConfig.PidsLimit}}' "$name"
  run docker exec "$name" python3 /diag/cgroup_lab.py facts --try-write
  run docker exec "$name" python3 /diag/cgroup_lab.py setup
  echo "a docker exec after the move lands in: $(docker exec "$name" cat /proc/self/cgroup 2>&1)"
  echo "a docker exec -u 65534 lands in: $(docker exec -u 65534 "$name" cat /proc/self/cgroup 2>&1)"
  run docker exec "$name" python3 /diag/cgroup_lab.py checks
  local since
  since="$(date +%s)"
  run docker exec "$name" python3 /diag/cgroup_lab.py oom --budget-mb 128
  run docker exec "$name" python3 /diag/cgroup_lab.py dying --mb 256
  if [ "${PROBE_GPU:-0}" = 1 ]; then
    run docker exec "$name" python3 /diag/cgroup_lab.py gpu --gib "${PROBE_GPU_GIB:-4}"
  fi
  echo "docker stats: $(docker stats --no-stream --format '{{.MemUsage}} {{.PIDs}} pids' "$name" 2>&1)"
  echo "docker events since the OOM test: $(docker events --since "$since" --until "$(date +%s)" --filter container="$name" --format '{{.Action}}' | sort | uniq -c | tr '\n' ' ')"
  docker stop -t 5 "$name" > /dev/null
  echo "after docker stop, State.OOMKilled: $(docker inspect -f '{{.State.OOMKilled}}' "$name")"
  docker rm -f "$name" > /dev/null
}

section "2. the same, plus --security-opt writable-cgroups=true --cgroupns private"
probe_writable "$TAG-writable"

section "3. the same under a container limit, as CI's mem_limit, memswap_limit and pids_limit"
probe_writable "$TAG-limited" --memory 2g --memory-swap 2g --pids-limit 4096

section "4. compose: security_opt [writable-cgroups=true] and cgroup: private"
export DIAG_IMAGE="$IMAGE"
run docker compose -p "$TAG-compose" -f "$HERE/compose.yml" up -d
run docker compose -p "$TAG-compose" -f "$HERE/compose.yml" exec -T probe python3 /diag/cgroup_lab.py facts --try-write
run docker compose -p "$TAG-compose" -f "$HERE/compose.yml" exec -T probe python3 /diag/cgroup_lab.py setup
echo "a docker compose exec after the move lands in: $(docker compose -p "$TAG-compose" -f "$HERE/compose.yml" exec -T probe cat /proc/self/cgroup 2>&1)"
run docker compose -p "$TAG-compose" -f "$HERE/compose.yml" exec -T probe python3 /diag/cgroup_lab.py oom --budget-mb 128
docker compose -p "$TAG-compose" -f "$HERE/compose.yml" down -t 5 > /dev/null 2>&1

section "done"
docker ps -a --filter "name=$TAG" --format '{{.Names}}' | xargs -r docker rm -f
