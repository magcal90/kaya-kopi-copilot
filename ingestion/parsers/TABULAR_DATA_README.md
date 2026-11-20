# Daily outlet CSV parser

`ingestion.parsers.tabular` maps the four source CSV schemas into one loss-aware dataset while retaining
raw values, source hashes, row locators, and validation results.

Run it from the repository root:

```bash
.venv/bin/python -m ingestion.parsers.tabular
```

Outputs:

- `runtime/structured/daily_outlet_summaries.csv`: normalized daily records; and
- `runtime/structured/tabular_quality_issues.csv`: invalid-row and missing-date warnings.

The parser applies a date format per source schema. In particular, `Business Date` is parsed as
month/day/year, while `Date` is parsed as day/month/year. Following the client clarification,
`Total Sales`, `sales$`, `REVENUE`, and `Gross Takings` normalize to GST-inclusive gross takings,
and `No of Cups`, `txns`, `CUPS`, and `Customer Count` normalize to receipt counts. The source labels
and raw values remain in staging for lineage. Missing dates are warnings and mean missing reports,
not zero sales or outlet closure; they are excluded from averages.

These daily facts should be queried through a structured database tool rather than embedded as one
vector per row. `record_id`, `source_file`, and `source_locator` allow the tool response to cite the
original CSV row.
