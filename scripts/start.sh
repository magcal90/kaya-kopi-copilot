#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

./scripts/check_environment.sh
if ! grep -Eq '^OPENAI_API_KEY=.+$' .env; then
  echo "error: OPENAI_API_KEY is empty or missing in .env" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

docker compose up -d mysql
mysql_command=(docker compose exec -T -e "MYSQL_PWD=$KAYA_DB_ROOT_PASSWORD" mysql mysql -uroot)
loaded=0
for _ in $(seq 1 30); do
  if [[ "$("${mysql_command[@]}" --batch --skip-column-names --execute="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$KAYA_DB_NAME' AND table_name='source_document';" 2>/dev/null || true)" == "1" ]]; then
    loaded=1
    break
  fi
  sleep 2
done
if [[ "$loaded" -ne 1 ]]; then
  echo "error: the application database is not loaded; run ./scripts/reload_data.sh first" >&2
  exit 2
fi

docker compose up -d --build copilot

echo "Kaya Kopi copilot is starting at http://localhost:${KAYA_STREAMLIT_HOST_PORT:-8501}"
echo "View logs with: docker compose logs -f copilot"
echo "Stop it with:   docker compose down"
