# Invoice OCR and parsing

`ingestion.parsers.invoice_ocr` reads images recursively from `data/images` and writes OCR results to
`runtime/ocr`, preserving the input directory structure.

## Setup

Create a virtual environment and install PaddleOCR with its CPU runtime:

```bash
sudo apt-get install python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install -r ingestion/requirements-ocr.txt
```

Using `.venv` avoids Debian/Ubuntu's `externally-managed-environment` error and
keeps project packages separate from the system Python installation. Do not use
`--break-system-packages` for this project.

## Run

```bash
.venv/bin/python -m ingestion.parsers.invoice_ocr
```

Add `--write-text` for plain-text sidecars, or `--overwrite` to reprocess existing
results. The default PaddleOCR model is English; pass `--language ch` for Chinese and
English documents. Run `.venv/bin/python -m ingestion.parsers.invoice_ocr --help` for all
options. The first run downloads the selected PaddleOCR detection and recognition
models and later runs reuse the local model cache.

The primary output is one `<original-name>.ocr.json` file per image. JSON is preferred
over plain text because it preserves the extracted text, word confidence, bounding
boxes, OCR settings, dimensions, source path, and processing timestamp. This supports
auditing low-confidence invoice fields and later loading into a database. Optional
`.ocr.txt` files are convenient for manual review but should not be the canonical data.

## Convert OCR to structured CSV

After OCR completes, create one invoice-header file and one invoice-line file:

```bash
.venv/bin/python -m ingestion.parsers.invoice
```

This writes `runtime/structured/invoices.csv` and
`runtime/structured/invoice_items.csv`. The parser uses the bounding boxes in
the JSON sidecars to recover table columns, validates invoice and line arithmetic,
and marks incomplete or inconsistent rows as `REVIEW_REQUIRED` rather than guessing.
The invoice CSV includes document-level OCR metadata (engine, language, processing
time, image dimensions, confidence, source, and sidecar path). Detailed region boxes
and polygons remain in the canonical JSON sidecars rather than being duplicated in CSV.
