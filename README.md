````markdown
# Lucrum

Lucrum is a FastAPI service that helps procurement teams plan warehouse replenishment. It analyzes sales history, stock levels, goods in transit, and supplier terms to recommend quantities for review.

The service addresses two common problems with spreadsheet-based purchasing:

- Replenishment calculations can be infrequent and difficult to repeat consistently.
- A one-off large sale can inflate apparent regular demand and distort later orders.

Lucrum smooths isolated sales spikes when estimating regular demand and provides a justification for each recommended line. Recommendations remain **pending until a responsible employee explicitly approves them**. The backend does not send orders to suppliers.

## Project status

The backend includes:

- Monthly demand forecasting with seasonality, capped trend adjustments, and stockout compensation.
- Anomaly filtering for unusually large purchases associated with an anonymized client token.
- Replenishment calculations that account for on-hand stock, goods in transit, supplier lead time, and minimum order quantity (MOQ).
- FastAPI endpoints for calculation, stock status, approvals, and 1C-compatible CSV export.
- SQLite persistence for calculation runs and approval decisions.
- XLSX loading from `data/raw/`, with a deterministic synthetic dataset fallback when startup inputs are missing or malformed.
- An XLSX upload endpoint that reloads the dataset after a successful parse.

## Data sources and mapping

Place partner workbooks in `data/raw/`. The loader scans workbook sheets and checks header rows 0–5 to handle common header offsets. It recognizes source roles from workbook names and, where possible, from column headers.

The supplied files are organized by these source roles:

| Source | Example workbooks | Purpose |
| --- | --- | --- |
| Monthly sales | `Ежемесячные продажи в количественном выражении за последние 2 года (2).xlsx`, `Ежемесячные продажи в кол-м выражении SystemElectric 2024-2026 (2).xlsx` | Historical monthly sales by item |
| Sales dynamics | `Динамика продаж_2025-2026 (2).xlsx`, `Динамика продаж_Syseme Electric_2025-2026 (2).xlsx` | More detailed sales history where available |
| Historical stock | `Ежемесячные остатки продукции за последние 2 года  ИЭК (2).xlsx`, `Ежемесячные остатки SystemElectric 2024-2026 (2).xlsx` | Stock history for current stock and stockout analysis |
| Goods in transit | `Путь ИЭК 22.09.2026 (2).xlsx`, `Товар в пути_SystemElectric на 22.09.2026 (2).xlsx` | Incoming quantities |
| Supplier terms and MOQ | `MOQ  ИЭК (2).xlsx`, `MOQ SystemElectric (2).xlsx` | Product-to-supplier information and minimum order quantities |
| Seasonality reports | `Сезонность ИЭК (2).xlsx`, `Сезонность SystemElectric 2024-2026 (2).xlsx` | Reference reports; the forecasting engine estimates seasonality from monthly sales history |

Sales-dynamics workbooks are not summed in addition to monthly sales workbooks when both are present, to avoid double-counting. Seasonality reports are not treated as additional sales. The engine estimates seasonal effects from the sales series.

### Data requirements

Use consistent identifiers and units across workbooks:

| Data | Required or useful fields |
| --- | --- |
| Sales | Month or date, SKU/article code, quantity, warehouse when available |
| Stock | SKU/article code, warehouse, quantity, snapshot date |
| Goods in transit | SKU/article code, destination warehouse, open quantity; delivery date and status when available |
| Supplier terms | SKU/article code, supplier code, supplier name, lead time in days, MOQ when applicable |
| Product details | SKU/article code, product name, category, unit of measure |
| Stockouts | SKU/article code, warehouse, start date, end date; may be derived from dated zero-stock records |
| BOM | Parent SKU, component SKU, component quantity, unit of measure, and matching 1C item codes |

For transaction-level sales data, use one row per sales line. Quantities should be numeric, dates should be actual Excel dates or unambiguous values such as `YYYY-MM-DD`, and product quantities should use a consistent unit of measure.

Use anonymized client tokens only, for example `CLIENT_000123`. Do not include customer names, phone numbers, email addresses, physical addresses, or other personally identifiable information. The loader excludes recognized client and contact columns; do not rely on that as a substitute for removing sensitive information before sharing workbooks.

The loader defaults a missing supplier lead time to 30 days and a missing product category to `uncategorized`, with an aggregate warning for missing lead times. It prefers explicit supplier fields when present. The supplied IEK and SystemElectric sales/MOQ books identify product ranges but do not contain a separate legal supplier directory, so the loader currently uses `IEK` and `SYSTEMELECTRIC` as provisional supplier codes/names for those ranges. These are grouping keys, not verified 1C supplier-directory codes; provide an authoritative supplier crosswalk before relying on the export as a production 1C import. The current partner files do not clearly identify a separate lead-time directory or BOM workbook; add and map those sources if they are available. The engine has a BOM data model, but the partner XLSX adapter does not currently load an unmapped BOM workbook.

Do not commit confidential partner workbooks to a public repository. Source XLSX files under `data/raw/` are ignored by Git. Keep shared examples synthetic or appropriately anonymized.

### Loader behavior

- Workbook roles are identified from filenames and, for generic filenames, recognizable headers.
- The loader selects recognized columns and aggregates sales by SKU, warehouse, and month.
- Consecutive zero-stock months are converted into stockout intervals.
- Missing or malformed startup inputs produce a warning and activate the deterministic synthetic dataset.
- `POST /api/upload` uses strict loading: an invalid workbook is rejected, removed from `data/raw/`, and does not replace the active dataset.
- After a successful upload, previous recommendations are invalidated. Run a new calculation before approving or exporting recommendations based on the updated data.

## Architecture and technology

- **FastAPI** provides the versioned JSON API and interactive OpenAPI documentation.
- **Pydantic** defines and validates request and response models.
- **SQLite**, accessed with Python’s standard-library `sqlite3`, persists calculation runs, recommendation rows, approval status, timestamps, approver identifiers, and manager notes. The project does not currently use SQLAlchemy.
- **Pandas** and **OpenPyXL** inspect and parse Excel workbooks.
- **Uvicorn** runs the ASGI application.
- **Pytest** and FastAPI’s `TestClient` cover engine and API behavior.

Useful references:

- [API contract](docs/API.md)
- [Calculation methodology](docs/METHODOLOGY.md)
- [Synthetic sample data](data/sample/README.md)

## Prerequisites

- Python 3.10 or newer
- Git
- Access to the partner XLSX files, if testing with real inputs

## Installation

Clone the repository using your project’s repository URL:

```bash
git clone <repository-url>
cd Lucrum
```

Create and activate a virtual environment.

**Windows PowerShell:**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS or Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

To use partner data, place the permitted XLSX workbooks in `data/raw/`. If no usable partner inputs are present, the service starts with synthetic sample data.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `LUCRUM_RAW_DIR` | `data/raw/` under the repository root | Directory scanned for partner XLSX workbooks |
| `LUCRUM_DB_PATH` | `data/lucrum.sqlite3` under the repository root | SQLite database path |

Relative override paths are resolved from the application’s current working directory. Set environment variables before starting Uvicorn.

**PowerShell example:**

```powershell
$env:LUCRUM_RAW_DIR = "C:\path\to\partner-workbooks"
$env:LUCRUM_DB_PATH = "C:\path\to\lucrum.sqlite3"
```

## Running the application

From the repository root, start the development server:

```bash
uvicorn backend.app:app --reload
```

The service is available at `http://127.0.0.1:8000`. Open Swagger UI at `http://127.0.0.1:8000/docs` or the OpenAPI schema at `http://127.0.0.1:8000/openapi.json`.

Generate the canonical synthetic CSV examples with:

```bash
python scripts/generate_sample.py
```

These examples are for development and testing. They are not loaded automatically by the API; the loader’s built-in fallback is generated in memory.

## API overview

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Health check |
| `POST /api/calculate` | Calculate recommendations; optional `warehouse` and `category` filters |
| `GET /api/orders` | Return the latest persisted calculation grouped by supplier |
| `POST /api/orders/approve` | Explicitly approve pending items by item ID and/or supplier code |
| `GET /api/orders/export-1c` | Download approved items from the latest calculation as CSV |
| `POST /api/upload` | Upload an XLSX workbook and reload the active dataset |
| `GET /api/stock` | Return stock status; optional `warehouse` filter |

See [docs/API.md](docs/API.md) for request and response examples, fields, and error behavior.

## Core workflow and verification

### 1. Load data and calculate recommendations

Start Uvicorn and open `/docs`. If using real workbooks, confirm that the server log reports the expected inputs. Otherwise, the synthetic fallback provides sample recommendations.

In Swagger UI:

1. Run `POST /api/calculate`. Optionally set `warehouse` or `category`.
2. Note the returned order `id`, `supplier_code`, and `warehouse`.
3. Use `GET /api/orders` to review lines grouped by supplier, including status and justification.
4. Do not run another calculation before approving the selected IDs: approvals apply to the latest calculation run.

A new calculation creates new pending recommendation records in SQLite.

### 2. Approve an order explicitly

Use `POST /api/orders/approve` with an item ID or supplier code and explicit confirmation. Example:

```json
{
  "item_ids": ["d12a696c-264c-4d63-a59e-639e644208b8"],
  "supplier_codes": ["SUP-001"],
  "confirmed": true,
  "manager_note": "Проверено, товар в наличии",
  "approved_by": "John Doe"
}
```

For the first approval, the response places the ID in `approved` and records the approval timestamp and approver. Repeating the same request returns HTTP 200, places the ID in `already_approved`, and preserves the original approval metadata. An approval records a decision only; it never sends an order to a supplier.

### 3. Export approved positions for 1C

Use `GET /api/orders/export-1c` to download approved positions from the latest calculation. The CSV columns are:

```text
SupplierCode,SKU,Quantity,Warehouse
```

`SupplierCode` uses the stored supplier code. If that value is blank or marked unknown, the stored supplier name is used as a fallback. Optional filters are `date` (approval date in `YYYY-MM-DD` format), `supplier_code`, and `warehouse`.

If no approved positions match the latest calculation and filters, the endpoint returns HTTP 404 with:

```json
{"detail": "No approved positions found for export"}
```

The export is a file only. It does not transmit orders to suppliers.

### 4. Upload an updated workbook

Use `POST /api/upload` in Swagger UI. Select one `.xlsx` file in the `file` form field. Uploads are limited to 25 MiB. After successful validation, the file is stored under `data/raw/` with a generated filename and the dataset is reloaded. A new calculation is required before approving or exporting recommendations based on the updated data.

## Regression tests

Install project requirements, then run the test suite from the repository root:

```bash
pytest
```

The tests cover forecasting behavior, stock and transit effects, stockout compensation, BOM engine behavior, anomaly filtering, API filters, approval idempotency and audit fields, XLSX upload handling, and 1C export mapping and empty-result behavior.

## Persistence and operational notes

- SQLite stores calculation runs and line-item recommendations. New calculations start with `pending` status.
- Approval records `approved_by`, `approved_at`, `approval_timestamp`, and an optional manager note.
- Repeating approval is idempotent. Rejected states are permitted by the database schema, though a rejection endpoint is not currently exposed.
- Approval and export are scoped to the latest calculation run. A new calculation or successful upload makes earlier recommendations ineligible for the current export.
- The API has no supplier-send endpoint. Procurement staff remain responsible for reviewing and approving recommendations and for any external order submission.
````
