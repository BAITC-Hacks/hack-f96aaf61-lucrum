# API contract v1

The API calculates and returns recommendations, stores them in SQLite, and records an explicit manager approval decision. It has no supplier-send operation. JSON field names and response shapes below are the v1 contract.

## `POST /api/calculate`

Optional query parameters: `warehouse` and `category` (exact identifiers). Recalculates recommendations against the currently loaded data and returns:

```json
{
  "api_version": "v1",
  "orders": [{
    "sku": "SKU-001", "product_name": "Example", "category": "cables",
    "warehouse": "WH-01", "unit": "pcs", "supplier_code": "SUP-01",
    "supplier_name": "Example supplier", "quantity": 18,
    "forecast_monthly_demand": 30.0, "urgency": "high",
    "justification": ["Forecast demand: 30.00 pcs/month."],
    "id": "c620d134-...", "status": "pending",
    "approval_timestamp": null, "manager_note": null
  }]
}
```

Each order line retains product and supplier codes needed for downstream 1C mapping. `urgency` is `high` or `normal`.

## `GET /api/orders`

Returns the latest persisted calculation, grouped by supplier. Lines include their stable `id`, `status`, approval timestamp, and manager note. At process startup, recognized XLSX workbooks are loaded from `data/raw/` or `LUCRUM_RAW_DIR` when set:

```json
{"api_version":"v1","suppliers":[{"supplier_code":"SUP-01","supplier_name":"Example supplier","items":[{"sku":"SKU-001","quantity":18}]}]}
```

Items contain the complete order-line object from `/api/calculate`.

## `POST /api/orders/approve`

Approves pending item IDs and/or all pending items for the listed supplier codes in the latest calculation. `confirmed: true` is required to represent the manager's explicit confirmation. The optional `approved_by` identifier defaults to `manager`; approval records `approved_at` (UTC) and the optional note. Repeating an approval is idempotent and returns HTTP 200 with an `already approved` message. Approval never sends anything to a supplier.

```json
{"item_ids": ["d12a696c-264c-4d63-a59e-639e644208b8"], "supplier_codes": ["SUP-001"], "confirmed": true, "manager_note": "Проверено, товар в наличии", "approved_by": "John Doe"}
```

The typed response contains `api_version`, `run_id`, newly approved item IDs, already-approved item IDs, their timestamps and approvers, and `status: "approved"`. A repeated approval returns the original timestamp and approver. Missing confirmation returns HTTP 400; no matching rows returns HTTP 409. Swagger includes a ready-to-use example request body.

## `GET /api/orders/export-1c`

Downloads a UTF-8 CSV containing only approved lines from the latest calculation. Optional query filters are `date` (approval date, `YYYY-MM-DD`), `supplier_code`, and `warehouse`. The `SupplierCode` value comes from the stored supplier code, falling back to the stored supplier name only when the code is blank or marked unknown. Columns are `SupplierCode`, `SKU`, `Quantity`, and `Warehouse`. No matching approved positions returns HTTP 404. Exporting never sends an order.

## `POST /api/upload`

Accepts one `.xlsx` workbook as multipart/form-data in the `file` field (maximum 25 MiB). The workbook is stored under `data/raw/` using a generated collision-safe filename, then the full raw directory is reloaded. The active dataset changes only after parsing succeeds; a failed load removes the uploaded file and returns HTTP 422. The response includes the stored filename and loaded record counts. A new calculation is required before newly loaded data appears in recommendations.

## `GET /api/stock?warehouse=WH-01`

Returns current stock rows, optionally filtered by warehouse:

```json
{"api_version":"v1","items":[{"sku":"SKU-001","warehouse":"WH-01","quantity":12,"stockout":false}]}
```

## `GET /api/health`

Returns `{"status":"ok","api_version":"v1"}`. The loader reads XLSX files from `data/raw/` or `LUCRUM_RAW_DIR`; when inputs are missing or a workbook is malformed, it logs a warning and uses deterministic synthetic data. SQLite is stored at `data/lucrum.sqlite3` by default; `LUCRUM_DB_PATH` overrides it. The service intentionally exposes no endpoint that sends orders.
