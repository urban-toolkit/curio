#!/usr/bin/env bash
# Remove the Docker images CI jobs leave on a self-hosted runner's daemon.
# stop-stack runs it at the end of every job that starts a stack.
#
# Every commit brings an image of several GB, pulled by start-stack or built by
# the job (test-gpu, test-gpu-stress). An arcade runner's daemon is its own;
# utk-gpu's is the host's, which the deployed stacks share, and a utk-desktop
# runner's is its desktop's. Removed:
# - the CI stacks' image names, `curio-ci*-curio` (start-stack tags them,
#   compose builds under them), which otherwise hold their last jobs' images
#   for good, one per project;
# - the pulled images of other commits (this commit's stays for the runner's
#   next job of the same commit);
# - untagged images no container uses, and build cache no build has used for
#   a day.
# On an arcade runner the job's own name stays on its image: the next job of
# the project shares most of its layers (the base, and the libraries
# `curio.py setup` installs), so it pulls or unpacks only what changed, and
# when it moves the name the old image is left untagged and goes. And there a
# job that has no image of its own, because it failed or was cancelled before
# its pull or build, removes no name and no image of another commit, so the
# image an earlier job left stays for the runner's next job. A job has one
# once CURIO_CI_OWN_IMAGE is 1: start-stack sets it after its pull, and a job
# that builds its image after the build. utk-gpu and the utk-desktop runners
# keep no CI image between jobs.
#
# The deployed stacks' images and every image a container uses stay:
# `docker image rm` without -f skips an image in use. The disk use before and
# after goes to the job's log.
#
#   bash scripts/ci_image_cleanup.sh <compose project>
# with RUNNER_NAME, GITHUB_REPOSITORY and GITHUB_SHA as the runner sets them.
set -u

project=$1
repo="ghcr.io/$(printf '%s' "$GITHUB_REPOSITORY" | tr '[:upper:]' '[:lower:]')-ci"
arcade=false
[[ "${RUNNER_NAME:-}" == arcade-* ]] && arcade=true

echo "Docker disk use before the cleanup:"
docker system df || true

if [[ "$arcade" == false || "${CURIO_CI_OWN_IMAGE:-}" == 1 ]]; then
  names=$(docker image ls --format '{{.Repository}}:{{.Tag}}' | grep -E '^curio-ci(-[a-z-]+)?-curio:' || true)
  if [[ "$arcade" == true ]]; then
    names=$(printf '%s\n' "$names" | grep -v "^${project}-curio:" || true)
  fi
  printf '%s\n' "$names" | xargs -r docker image rm > /dev/null 2>&1 || true
  docker image ls "$repo" --format '{{.Repository}}:{{.Tag}}' \
    | { grep -v ":${GITHUB_SHA}\$" || true; } \
    | xargs -r docker image rm > /dev/null 2>&1 || true
else
  echo "This job has no image of its own, so the images an earlier job left stay."
fi

docker image prune -f > /dev/null 2>&1 || true
docker builder prune -af --filter until=24h > /dev/null 2>&1 || true
echo "Docker disk use after the cleanup:"
docker system df || true
