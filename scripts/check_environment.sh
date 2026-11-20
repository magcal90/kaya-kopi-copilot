#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

[[ -f .env ]] || {
  echo "error: .env is missing; copy .env.example to .env and configure it" >&2
  exit 2
}

command -v docker >/dev/null 2>&1 || {
  echo "error: Docker is not installed or is not on PATH" >&2
  exit 2
}
docker compose version >/dev/null 2>&1 || {
  echo "error: Docker Compose v2 is required" >&2
  exit 2
}

required_variables=(
  KAYA_DB_NAME KAYA_DB_USER KAYA_DB_PASSWORD KAYA_DB_ROOT_PASSWORD
)
for variable in "${required_variables[@]}"; do
  if ! grep -Eq "^${variable}=.+$" .env; then
    echo "error: $variable is empty or missing in .env" >&2
    exit 2
  fi
done

if [[ "${1:-}" == "--require-data" ]]; then
  required_paths=(
    "data/sql/kayakopi_pos.sql"
    "data/tabular/staff_roster_jun2026.xlsx"
    "data/images/supplier_invoices"
    "data/docs"
  )
  missing=0
  for required_path in "${required_paths[@]}"; do
    if [[ ! -e "$required_path" ]]; then
      echo "error: required data path is missing: $required_path" >&2
      missing=1
    fi
  done
  [[ "$missing" -eq 0 ]] || exit 2
fi
