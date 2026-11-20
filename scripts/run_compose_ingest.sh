#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

export KAYA_DOCKER_UID="${KAYA_DOCKER_UID:-$(id -u)}"
export KAYA_DOCKER_GID="${KAYA_DOCKER_GID:-$(id -g)}"

exec "$project_dir/scripts/reload_data.sh"
