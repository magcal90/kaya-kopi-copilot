#!/usr/bin/env bash
set -euo pipefail

: "${KAYA_DB_HOST:=mysql}"
: "${KAYA_DB_PORT:=3306}"
: "${KAYA_DB_USER:?KAYA_DB_USER is required}"
: "${KAYA_DB_PASSWORD:?KAYA_DB_PASSWORD is required}"
: "${KAYA_DB_NAME:=kayakopi}"

python -m ingestion.parsers.invoice_ocr
python -m ingestion.parsers.invoice
python -m ingestion.parsers.text_documents
python -m ingestion.parsers.tabular
python -m ingestion.parsers.staff_roster
python -m ingestion.loader.mysql
