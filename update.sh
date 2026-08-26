#!/usr/bin/env bash
#
# Update a running deployment: fetch the committed code, stop the containers,
# then rebuild and start them.
#
# Run it from anywhere. The script works out the project directory from its own
# location, so it does not matter which folder your shell is in.
#
#   ./update.sh
#
# `set -e` stops at the first failure. That matters here: if `git pull` fails,
# rebuilding would quietly redeploy the old code and look like it worked.
# `set -u` catches typos in variable names, and `pipefail` stops a failure in
# the middle of a pipe from being hidden by a success at the end.
set -euo pipefail

project_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_directory"

echo "==> Updating $project_directory"

git pull
docker compose down
docker compose up -d --build

echo
echo "==> Running containers"
docker compose ps
