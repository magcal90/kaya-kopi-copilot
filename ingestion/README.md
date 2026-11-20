# Ingestion module

The ingestion path keeps the supplied MySQL tables unchanged and adds the parsed-data tables from
the canonical ERD.

The parsed sources include the eight daily-summary CSVs, the private June 2026 staff-roster XLSX,
invoice OCR sidecars, and email/WhatsApp documents. The roster workbook remains under ignored
`data/`; generated staging rows retain source-row lineage and must not be committed.

## Docker-first workflow

```bash
./scripts/bootstrap.sh
./scripts/reload_data.sh
```

Docker installs the requirements into isolated images. A host `.venv` is not required.

## Explicit purge and reload

```bash
./scripts/reload_data.sh
```

The reload script starts MySQL, drops the existing application database, imports
`data/sql/kayakopi_pos.sql`, applies `ingestion/schema/schema.sql`, reruns OCR and every parser,
and loads the normalized data.

Because the supplied legacy dump contains `DROP TABLE` statements, the complete setup command
recreates the four legacy tables from that dump. Use the individual schema/loader commands when the
legacy tables must not be reset.

Generated OCR and structured files are written under ignored `runtime/`. The reload wrapper passes
the current host UID and GID so those files retain the correct ownership.

## Run individual stages

```bash
docker compose --profile setup run --rm ingest
```

The full scripts run `ingestion.parsers.staff_roster` before the loader. To regenerate only its
private staging artifacts:

```bash
docker compose --profile setup run --rm ingest python -m ingestion.parsers.staff_roster
```

Connection settings can be overridden with `KAYA_DB_HOST`, `KAYA_DB_PORT`, `KAYA_DB_USER`,
`KAYA_DB_PASSWORD`, and `KAYA_DB_NAME`.

The loader uses stable import keys and `ON DUPLICATE KEY UPDATE`, so rerunning it updates matching
records without creating duplicates. Following the client decision, reconciliation requires the
canonical supplier code, invoice number, date, and closest amount. Every legacy purchase receives a
reconciliation row; unmatched purchases are retained as `NO_SCAN`. The reused Mewah invoice number
therefore keeps both genuine purchases while linking the 5 September scan to only one of them.
