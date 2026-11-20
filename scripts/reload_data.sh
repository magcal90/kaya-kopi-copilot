#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

./scripts/check_environment.sh --require-data
set -a
# shellcheck disable=SC1091
source .env
set +a

identifier_pattern='^[A-Za-z0-9_]+$'
credential_pattern='^[A-Za-z0-9_.@%+-]+$'
[[ "$KAYA_DB_NAME" =~ $identifier_pattern ]] || { echo "error: unsafe KAYA_DB_NAME" >&2; exit 2; }
[[ "$KAYA_DB_USER" =~ $identifier_pattern ]] || { echo "error: unsafe KAYA_DB_USER" >&2; exit 2; }
[[ "$KAYA_DB_PASSWORD" =~ $credential_pattern ]] || {
  echo "error: KAYA_DB_PASSWORD may contain letters, numbers, and ._@%+- only" >&2
  exit 2
}

export KAYA_DOCKER_UID="${KAYA_DOCKER_UID:-$(id -u)}"
export KAYA_DOCKER_GID="${KAYA_DOCKER_GID:-$(id -g)}"
mkdir -p runtime/ocr runtime/structured

docker compose up -d mysql
mysql_command=(docker compose exec -T -e "MYSQL_PWD=$KAYA_DB_ROOT_PASSWORD" mysql mysql -uroot)

ready=0
for _ in $(seq 1 30); do
  if "${mysql_command[@]}" --execute="SELECT 1" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" -eq 1 ]] || { echo "error: MySQL did not become ready within 60 seconds" >&2; exit 1; }

echo "Reloading $KAYA_DB_NAME from private source data..."
"${mysql_command[@]}" --execute="DROP DATABASE IF EXISTS \`$KAYA_DB_NAME\`;"
"${mysql_command[@]}" < data/sql/kayakopi_pos.sql
"${mysql_command[@]}" < ingestion/schema/schema.sql
"${mysql_command[@]}" --execute="CREATE USER IF NOT EXISTS '$KAYA_DB_USER'@'%' IDENTIFIED BY '$KAYA_DB_PASSWORD'; ALTER USER '$KAYA_DB_USER'@'%' IDENTIFIED BY '$KAYA_DB_PASSWORD'; GRANT ALL PRIVILEGES ON \`$KAYA_DB_NAME\`.* TO '$KAYA_DB_USER'@'%'; FLUSH PRIVILEGES;"

docker compose --profile setup run --rm --build ingest
echo "Reload complete. Run ./scripts/test.sh, then ./scripts/start.sh."
