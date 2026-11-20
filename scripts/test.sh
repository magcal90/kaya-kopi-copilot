#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

./scripts/check_environment.sh
docker compose up -d mysql
docker compose --profile test run --rm --build test
