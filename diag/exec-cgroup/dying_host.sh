#!/usr/bin/env bash
# Do removed node cgroups linger while the page cache they charged lives? (a
# diagnostic). One writable-cgroups container, ten cgroups each caching 50 MB;
# writes only inside the container's own cgroup; removes the container.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="diag-cgroup-${GITHUB_RUN_ID:-local}-${PROBE_NAME:-host}-dying"
echo "kernel $(uname -r), docker $(docker version --format '{{.Server.Version}}')"
docker rm -f "$NAME" > /dev/null 2>&1
docker run -d --name "$NAME" --init --security-opt writable-cgroups=true --cgroupns private \
  -v "$HERE:/diag:ro" python:3.12-slim sleep infinity > /dev/null
docker exec "$NAME" python3 /diag/cgroup_lab.py setup
docker exec "$NAME" python3 /diag/cgroup_lab.py dying10 --mb 50
docker rm -f "$NAME" > /dev/null
