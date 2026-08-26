#!/usr/bin/env bash
#
# Update a running deployment: fetch the committed code and, only when that
# actually brought something new, rebuild and restart the containers.
#
# Rebuilding when nothing changed is not free. `docker compose down` stops the
# service, and the rebuild that follows takes it offline for as long as the
# image takes to build, all to arrive at exactly the code that was already
# running. So the common case, running this after nothing has been pushed,
# now leaves the containers untouched.
#
# Run it from anywhere. The script works out the project directory from its own
# location, so it does not matter which folder your shell is in.
#
#   ./update.sh            update only if `git pull` brought new commits
#   ./update.sh --force    rebuild and restart even when nothing changed
#
# `--force` is the escape hatch for the cases a commit hash cannot see: an
# edited `.env`, a base image that has moved under an unchanged Dockerfile, or
# a container in a bad state you want recreated.
#
# `set -e` stops at the first failure. That matters here: if `git pull` fails,
# rebuilding would quietly redeploy the old code and look like it worked.
# `set -u` catches typos in variable names, and `pipefail` stops a failure in
# the middle of a pipe from being hidden by a success at the end.
set -euo pipefail

project_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_directory"

force_rebuild=false
case "${1:-}" in
    --force) force_rebuild=true ;;
    "") ;;
    *)
        echo "usage: ${BASH_SOURCE[0]} [--force]" >&2
        exit 2
        ;;
esac

# Whether this Compose project has at least one container up right now. When
# nothing is running there is nothing to preserve, so a no-change pull should
# still start the service instead of leaving the machine with no deployment.
# The second command is the fallback for older Compose versions that do not
# accept `--status`.
containers_are_running() {
    local container_ids
    container_ids="$(
        docker compose ps --quiet --status running 2>/dev/null \
            || docker compose ps --quiet 2>/dev/null \
            || true
    )"
    [ -n "$container_ids" ]
}

echo "==> Updating $project_directory"

revision_before="$(git rev-parse HEAD)"
git pull
revision_after="$(git rev-parse HEAD)"

if [ "$revision_before" = "$revision_after" ] \
    && [ "$force_rebuild" = false ] \
    && containers_are_running; then
    echo "==> Already at ${revision_after:0:12}; nothing to deploy."
    echo "    Containers left running. Use --force to rebuild anyway."
    echo
    echo "==> Running containers"
    docker compose ps
    exit 0
fi

# Say which of the three reasons we are deploying, so a run that rebuilds
# without new commits does not look like the skip logic failed.
if [ "$revision_before" != "$revision_after" ]; then
    echo "==> New code: ${revision_before:0:12} -> ${revision_after:0:12}"
    git --no-pager log --oneline "$revision_before..$revision_after"
elif [ "$force_rebuild" = true ]; then
    echo "==> No new commits; rebuilding because --force was given"
else
    echo "==> No new commits, but nothing is running; starting the deployment"
fi

docker compose down
docker compose up -d --build

echo
echo "==> Running containers"
docker compose ps
