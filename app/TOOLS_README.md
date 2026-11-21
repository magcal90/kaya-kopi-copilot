# Kaya Kopi chatbot tools

The seven LangChain tools in `app.tools` expose fixed, read-only MySQL queries. They do not accept SQL
from the model and do not write to the database.

```python
from app.tools import ALL_TOOLS
```

Tools:

- `analyze_outlets_sql`: authoritative performance, measured wastage, and roster-based staffing;
- `analyze_pos_sql`: observed product mix, prices, payment modes, and time-of-day patterns from the explicitly partial POS export;
- `analyze_suppliers_sql`: scanned invoices, canonical spend, cost trends, item price changes, and purchase reconciliation;
- `get_data_coverage_sql`: objective source counts and completeness limitations;
- `search_documents_sql`: MySQL full-text search with substring fallback and entity filters;
- `assess_kopi_price_change_sql`: transparent price sensitivity scenarios with an insufficient-evidence decision state; and
- `get_data_quality_issues_sql`: bounded review queue with source citations.

The `_sql` suffix marks tools backed by the relational MySQL data. A future semantic retrieval tool
can use a distinct name such as `search_documents_vector`.

The older narrow Python functions remain importable as compatibility wrappers, but are not exposed
to the model in `ALL_TOOLS`. Sales analysis resolves effective aliases such as `AMK-3A` to `AMK-03`.
Daily Z-report summaries are authoritative for revenue where present; POS analysis is always marked
as partial. Structured facts come from MySQL and document results include source locators.

Install dependencies and run the database ingestion before importing the tools:

```bash
.venv/bin/python -m pip install -r app/requirements.txt
./scripts/run_compose_ingest.sh
```

Run the live MySQL smoke tests with:

```bash
.venv/bin/python -m unittest tests.integration.test_query_tools -v
```

## Streamlit copilot

The Streamlit application follows the `llm-rag-basic` tool-calling pattern: an OpenAI chat model
selects a tool, LangGraph executes the read-only database call, and the model turns the cited result
into an answer. Conversations persist in a local SQLite checkpoint database.

Set `OPENAI_API_KEY` in `.env`, then run from the repository root:

```bash
.venv/bin/python -m pip install -r app/requirements.txt
.venv/bin/streamlit run app/streamlit_app.py
```

The database tools themselves do not need an API key. The natural-language agent does, because the
LLM decides which tool and arguments to use. `KAYA_OPENAI_MODEL` optionally overrides the default
`gpt-4o-mini` model, and standard `OPENAI_BASE_URL` configuration is supported by LangChain.
