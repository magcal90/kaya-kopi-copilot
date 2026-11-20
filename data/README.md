# data/

Download YOUR team's zip from NTULearn (released at the Mon 16 Nov briefing) and unzip its
contents into this folder, so you end up with `data/sql/`, `data/tabular/`, `data/images/`,
`data/docs/` (exact folders vary by company).

Everything in this folder except this file is **git-ignored on purpose**. Client data never
enters git — a data file in your commit history costs marks and cannot be fully deleted.

For the packaged startup workflow, confirm these paths exist after copying the package:

```text
data/sql/kayakopi_pos.sql
data/tabular/staff_roster_jun2026.xlsx
data/images/supplier_invoices/
data/docs/
```

Do not copy generated `runtime/` files from another machine. `scripts/reload_data.sh` regenerates
OCR sidecars and normalized staging files from the private source package.
