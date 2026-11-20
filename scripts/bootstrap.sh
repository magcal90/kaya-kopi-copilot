#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

./scripts/check_environment.sh --require-data
mkdir -p runtime/ocr runtime/structured
docker compose --profile setup --profile test build

echo "Docker images are ready. Run ./scripts/reload_data.sh to load the private data."
