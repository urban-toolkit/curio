#!/usr/bin/env bash
# Remove the Docker images CI jobs leave on a self-hosted runner's daemon.
# stop-stack runs it at the end of every job that starts a stack, whether the
# job passed, failed or was cancelled, and build-image after a filtered run's
# collection. A job ended before its cleanup leaves its image to the next
# job's first step (`&reclaim` in the workflow), which removes the same names.
#
# Every commit brings an image, pulled by start-stack or built by the job
# (test-gpu, test-gpu-stress). An arcade runner's daemon is its own, but all
# 44 share arcade's one disk; utk-gpu's is the host's, which the deployed
# stacks share, and a utk-desktop runner's is its desktop's. No CI image
# outlives its job. Until 11-08 an arcade runner kept its last one, about
# 17 GB on disk, for its next job: about 750 GB of arcade's disk at rest, and
# when a new base image left a run's image no layer in common with them, 22
# jobs pulling a second one each filled the disk. Removed:
# - the CI stacks' image names, `curio-ci*-curio` (start-stack tags them,
#   compose builds under them);
# - every pulled CI image, this commit's too;
# - untagged images no container uses;
# - on an arcade CPU runner, whose daemon only CI uses and where no job builds
#   with it, all build cache; elsewhere the build cache no build has used for
#   a day. An arcade GPU runner keeps the rest of its cache for test-gpu, which
#   builds its image there: 27 to 40 s with it, 682 s without (11-08).
#
# The deployed stacks' images and every image a container uses stay:
# `docker image rm` without -f skips an image in use. The disk use before and
# after goes to the job's log, and the free disk after it.
#
#   bash scripts/ci_image_cleanup.sh
# with RUNNER_NAME and GITHUB_REPOSITORY as the runner sets them.
set -u

repo="ghcr.io/$(printf '%s' "$GITHUB_REPOSITORY" | tr '[:upper:]' '[:lower:]')-ci"

echo "Docker disk use before the cleanup:"
docker system df || true

docker image ls --format '{{.Repository}}:{{.Tag}}' \
  | { grep -E '^curio-ci(-[a-z-]+)?-curio:' || true; } \
  | xargs -r docker image rm > /dev/null 2>&1 || true
docker image ls "$repo" --format '{{.Repository}}:{{.Tag}}' \
  | xargs -r docker image rm > /dev/null 2>&1 || true

docker image prune -f > /dev/null 2>&1 || true
if [[ "${RUNNER_NAME:-}" == arcade-cpu-* ]]; then
  docker builder prune -af > /dev/null 2>&1 || true
else
  docker builder prune -af --filter until=24h > /dev/null 2>&1 || true
fi
echo "Docker disk use after the cleanup:"
docker system df || true
bash "$(dirname "$0")/ci_disk.sh" free "after the cleanup" || true
