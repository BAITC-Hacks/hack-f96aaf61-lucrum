# Elektrokomplekt procurement dashboard

Frontend for the Elektrokomplekt LLP supplier-order planning workflow. The app presents recommendations produced by the backend, lets a procurement manager review each line and adjust its quantity, and exports only manager-approved lines as a 1C-oriented CSV. Supplier dispatch is not implemented: no endpoint or UI action sends an order.

## Architecture

- **Frontend:** React + TypeScript + Vite. `src/ui` contains the responsive dashboard and review workflow; `src/data/api.ts` is the REST adapter; `src/data/mock.ts` contains clearly labeled synthetic development rows.
- **Backend:** separate service owned by Executor 1. This frontend treats `/api/calculate` and `/api/orders` as the source of truth. It does not calculate replenishment quantities.
- **Data flow:** the manager selects warehouse/category and runs a calculation. The frontend stores the returned `run_id` separately from each recommendation's item `id`, reads current stock separately, and displays the backend-provided rationale. Recalculation and successful upload invalidate local review state and lock approval until the new run is loaded. Immediately before approval, the frontend checks the latest `run_id` to catch changes made in another client. Individual checkboxes, the visible select-all checkbox, and supplier-group checkboxes all build an explicit list of item-level IDs; approval sends only those IDs in `item_ids`.
- **Safety:** no auto-send/dispatch code path exists. Export is local CSV download, never supplier delivery. The REST adapter maps an allow-list of fields into the UI model, rejects invalid records and rejects obvious PII indicators (email, phone-like strings, customer/contact keywords) without echoing the suspect value. Do not add raw API payload logging or pass arbitrary backend fields through the UI/export.

`src/components/OrderApprovalDashboard.vue` is a standalone Vue 3 Composition API version of the manager order workflow. The deployed dashboard entry point remains the React app in `src/ui`; the Vue SFC is not imported into that React tree and expects a Vue-enabled host.

## API integration contract

The frontend follows the supplied Lucrum backend API guide. Configure `VITE_API_BASE_URL` with the FastAPI origin. During Vite development, `/api` requests are proxied to that origin so the browser makes same-origin requests; production hosting needs a same-origin reverse proxy or backend CORS configuration. Requests have explicit timeouts and display FastAPI `detail` errors.

### `GET /api/orders`

```json
{
  "api_version": "v1",
  "run_id": "run-uuid",
  "suppliers": [
    {
      "supplier_code": "IEK",
      "supplier_name": "IEK",
      "items": [{ "id": "item-uuid", "sku": "SKU-001", "quantity": 18, "status": "pending" }]
    }
  ]
}
```

### `POST /api/calculate`

Optional exact-match filters are query parameters, not a JSON body:

```http
POST /api/calculate?warehouse=WH-01&category=cables
```

Response contains `api_version`, `run_id`, `created_at`, and an `orders` array. Each order contains `id`, `sku`, `product_name`, `category`, `warehouse`, `unit`, `supplier_code`, `supplier_name`, `quantity`, `forecast_monthly_demand`, `urgency`, `justification`, and approval metadata. A fresh calculation creates new IDs; prior item selections must be discarded.

### `POST /api/orders/approve`

The UI sends the explicitly reviewed pending IDs and requires the manager's confirmation click:

```json
{
  "item_ids": ["item-uuid"],
  "supplier_codes": [],
  "confirmed": true,
  "approved_by": "manager",
  "manager_note": "Reviewed"
}
```

The frontend submits `approved_by` and `manager_note` with the selected `item_ids`; notes are limited to 1,000 characters. Supplier-group selection is expanded to the visible pending item IDs and does not use the calculation's `run_id` as an item ID. The API does not accept adjusted quantities. The UI therefore blocks approval when a selected quantity differs from the backend recommendation and offers to restore the calculated quantity. A successful response marks accepted IDs approved and enables 1C export for those approved items. Approval is an audit decision only; the backend never dispatches orders to suppliers. A `409` refreshes the latest run and clears selection/review marks.

## 1C export

`GET /api/orders/export-1c` returns approved items only with columns `SupplierCode, SKU, Quantity, Warehouse` and an attachment filename from the backend. Optional exact filters are `date` (`YYYY-MM-DD`), `supplier_code`, and `warehouse`. The frontend checks content type, headers, field counts, and obvious PII indicators before download. A `404` with `No approved positions found for export` keeps the user in the approval flow.

### POST /api/upload

The frontend sends one multipart field named `file`. Only `.xlsx` workbooks up to 25 MiB are accepted. Successful upload invalidates the latest calculation; the old rows are removed and the manager must run `/api/calculate` before recommendations appear again. Failed parsing leaves the active backend dataset unchanged and the error is shown.

### `GET /api/health` and `GET /api/stock`

The dashboard checks health on load. `/api/stock` returns `items` with `sku`, `warehouse`, `quantity`, and `stockout`; these are joined by SKU and warehouse. If stock cannot be read, recommendations remain visible and the dashboard reports that stock data is unavailable.

## Replenishment methodology and outlier exclusion

**Not documented in the supplied project folder.** The folder contained source `.xlsx` files only; no Executor 1 technical write-up or backend methodology specification was available. The dashboard deliberately does not infer or restate calculation or anomaly-removal logic. Add Executor 1's approved explanation here, including the treatment of seasonality, demand growth, stockout intervals, in-transit inventory, BOM, lead times, and one-off/customer bulk-order outliers. Until then, the dashboard only displays the backend's recommendation and explanation; the synthetic development rows are not calculation outputs.

## Setup and run

Requirements: Node.js 20+ and npm. Install dependencies once at the repository root for the existing Tailwind/daisyUI toolchain, then run the frontend scripts from the frontend directory.

```sh
npm install
npm run dev
```

With `VITE_API_BASE_URL` unset, the app uses clearly labeled synthetic mock rows. To connect a local backend, copy `.env.example` to `.env.local`, set `VITE_API_BASE_URL=http://localhost:8000`, keep `VITE_API_PROXY=true`, and restart Vite. The dev server proxies `/api` to FastAPI, avoiding browser CORS during local development. For production, configure a same-origin proxy or enable the correct CORS origin on the backend. Mock mode cannot upload files or export backend approvals.

Production frontend build:

```sh
npm run build
npm run preview
```

Backend setup/run instructions must be supplied by Executor 1; no backend source, dependency manifest, or run guide was present in the folder. Do not derive an algorithm or backend command from the raw workbooks.

## Known limitations and assumptions

- Approval requests do not carry edited quantities in the documented API, so adjusted quantities cannot be approved until the backend adds support for them.
- Supplier codes IEK and SYSTEMELECTRIC may be provisional grouping keys rather than verified 1C directory IDs; the backend guide also notes a 30-day default lead time when source workbooks lack explicit lead times.
- The documented CSV columns are the backend's 1C export contract; verify them against the partner's actual import template before production.
- PII filtering detects common email/phone/contact indicators. Backend data should be anonymized at source and reviewed against the contract; heuristic checks cannot guarantee detection of every sensitive value.
- Current stock and stockout are read from `/api/stock`; monthly demand comes from the calculation response. In-transit balances and historical stock trends are not included in the supplied API contract.
- Authentication/authorization and supplier dispatch are outside this frontend; the backend must authorize approvals and validate/anonymize uploaded reports.
- A local backend was not bundled with this frontend; start FastAPI separately and ensure `VITE_API_BASE_URL` points to it.
