# WhatsApp and email parser

`ingestion.parsers.text_documents` converts the text files under `data/docs` into structured CSV files:

- `whatsapp_messages.csv`: one row per timestamped chat message;
- `emails.csv`: one row per email with parsed headers and body; and
- `document_chunks.csv`: a common retrieval format containing both messages and emails.

Run it from the repository root:

```bash
.venv/bin/python -m ingestion.parsers.text_documents
```

Each row retains its source file and exact source-line locator. The parser also extracts explicit
outlet-code and supplier-name mentions for database linking. It does not infer staff identities,
resolve outlet aliases, or convert operational claims into business transactions. Those actions
require validation against authoritative data.
