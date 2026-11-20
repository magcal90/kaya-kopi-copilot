# Kaya Kopi Data Context

This context distinguishes source evidence from validated business records used for reporting and
reconciliation.

## Language

**Source Document**:
An immutable version of an imported file that provides evidence for extracted records.
_Avoid_: OCR record, upload row

**Supplier Invoice**:
A supplier's request for payment, represented as a validated header and its item rows.
_Avoid_: Source document, OCR output

**Supplier Invoice Item**:
One billed product row belonging to a supplier invoice.
_Avoid_: OCR word, invoice document

**Supplier Purchase**:
A legacy purchase record that may be reconciled with a supplier invoice after validation.
_Avoid_: Invoice, automatic invoice match

**Daily Outlet Summary**:
One outlet's reported sales and operational measures for one business date.
_Avoid_: POS transaction, missing-day zero

**Gross Takings**:
The GST-inclusive daily revenue after refunds reported from an outlet's end-of-day Z-report.
_Avoid_: Complete POS revenue, ex-GST margin

**Receipt Count**:
The daily receipt count reported under source labels such as cups, transactions, or customer count.
_Avoid_: Drinks sold, unique customers

**Staff Assignment**:
One private roster row assigning a staff member and hourly rate to an outlet for a roster month.
_Avoid_: Employee master, public staff profile

**Staff Shift**:
One weekday shift pattern belonging to a staff assignment, retaining its raw code and paid hours.
_Avoid_: Clock-in record, actual attendance

**Outlet Alias**:
An alternate outlet code that resolves to one canonical outlet for an evidenced effective period.
_Avoid_: Source code, replacement outlet

**Document Chunk**:
A citable unit of document text used as one retrieval result.
_Avoid_: Source document, database answer

**Document Entity Mention**:
An explicit outlet or supplier reference found within a document chunk, whether resolved or unresolved.
_Avoid_: Verified business relationship

**Data Quality Issue**:
A recorded validation or coverage concern tied to source evidence.
_Avoid_: Deleted row, automatic correction

**Review Required**:
A validation state indicating that extracted evidence is incomplete, ambiguous, or arithmetically inconsistent.
_Avoid_: Invalid, rejected
