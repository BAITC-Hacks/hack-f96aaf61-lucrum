# Elektrokomplekt procurement dashboard

Frontend for the Elektrokomplekt LLP supplier-order planning workflow. The app presents recommendations produced by the backend, lets a procurement manager review each line and adjust its quantity, and exports only manager-approved lines as a 1C-oriented CSV. Supplier dispatch is not implemented: no endpoint or UI action sends an order.

## Architecture

- **Frontend:** React + TypeScript + Vite. `src/ui` contains the responsive dashboard and review workflow; `src/data/api.ts` is the REST adapter; `src/data/mock.ts` contains clearly labeled synthetic development rows.
- **Backend:** separate service owned by Executor 1. This frontend treats `/api/calculate` and `/api/orders` as the source of truth. It does not calculate replenishment quantities.
- **Data flow:** the manager selects warehouse/category and presses **Рассчитать потребность**. The frontend POSTs the scope, displays the returned recommendations and their backend-provided rationale, and permits quantity edits. Every line must be checked as reviewed before **Подтвердить заказ** is enabled. That explicit action marks the displayed recommendations approved in the frontend. Only then is CSV export enabled.
- **Safety:** no auto-send/dispatch code path exists. Export is local CSV download, never supplier delivery. The REST adapter maps an allow-list of fields into the UI model, rejects invalid records and rejects obvious PII indicators (email, phone-like strings, customer/contact keywords) without echoing the suspect value. Do not add raw API payload logging or pass arbitrary backend fields through the UI/export.

`src/components/OrderApprovalDashboard.vue` is a standalone Vue 3 Composition API version of the manager order workflow. The deployed dashboard entry point remains the React app in `src/ui`; the Vue SFC is not imported into that React tree and expects a Vue-enabled host.

## API integration contract (frontend expectation)

Configure `VITE_API_BASE_URL` as the backend origin. Requests use JSON and a 15-second timeout. Errors are shown to the user; the previous result remains visible if recalculation fails.

### `GET /api/orders`

```json
{
  "lines": [
    {
      "id": "opaque-line-id",
      "sku": "backend-sku",
      "bomId": "backend-bom-id",
      "product": "anonymized product description",
      "category": "category",
      "supplier": "supplier name/code",
      "warehouse": "warehouse name/code",
      "recommendedQty": 24,
      "unit": "шт",
      "urgency": "critical",
      "stock": 8,
      "monthlyUse": 15,
      "leadDays": 21,
      "justification": "backend-generated explanation",
      "seasonality": "backend-provided optional note",
      "moq": 12,
      "status": "pending"
    }
  ]
}
```

### `POST /api/calculate`

Request (scope fields are optional):

```json
{ "warehouse": "warehouse name/code", "category": "category" }
```

Response has the same `lines` structure as `GET /api/orders`, optionally with `calculationId` and `calculatedAt`. The backend owns scope interpretation, recommendation calculation, stock and trend values, urgency, BOM/SKU mapping, and justification. Optional seasonality and MOQ fields may be supplied for display. If Executor 1's final contract differs, update `src/data/api.ts` and this section before integration.

### POST /api/orders/approve

A procurement manager must review every displayed line and explicitly confirm it. The frontend sends adjusted quantities as { lines: [{ id, quantity }] }. Only a successful 2xx response marks lines approved. The backend must persist the authenticated approver, time, quantities, and audit event. The UI never calls a supplier-dispatch endpoint.

## 1C export

GET /api/orders/export-1c returns CSV for approved orders. The frontend validates the CSV content type, UTF-8 semicolon-delimited rows, exact SKU;BOM_ID;WAREHOUSE;SUPPLIER;QUANTITY;UNIT headers, field counts, and obvious PII indicators before download. Unexpected data is rejected without exposing the body. The backend must return approved orders only. Confirm the mapping against the partner 1C template before production.

### POST /api/upload

The frontend sends one multipart file field named file. It accepts XLSX, XLS, and CSV files up to 25 MB and does not display or log the selected filename or contents. The backend should validate and anonymize partner reports before returning data to the UI.

## Replenishment methodology and outlier exclusion

**Not documented in the supplied project folder.** The folder contained source `.xlsx` files only; no Executor 1 technical write-up or backend methodology specification was available. The dashboard deliberately does not infer or restate calculation or anomaly-removal logic. Add Executor 1's approved explanation here, including the treatment of seasonality, demand growth, stockout intervals, in-transit inventory, BOM, lead times, and one-off/customer bulk-order outliers. Until then, the dashboard only displays the backend's recommendation and explanation; the synthetic development rows are not calculation outputs.

## Setup and run

Requirements: Node.js 20+ and npm. Install dependencies once at the repository root for the existing Tailwind/daisyUI toolchain, then run the frontend scripts from the frontend directory.

```sh
npm install
npm run dev
```

With `VITE_API_BASE_URL` unset, the app uses clearly labeled synthetic mock rows and simulates a calculation locally. To connect a local backend, copy `.env.example` to `.env.local`, set `VITE_API_BASE_URL=http://localhost:8000` (or the actual backend origin), then restart Vite. The backend must allow the frontend origin through its CORS policy.

Production frontend build:

```sh
npm run build
npm run preview
```

Backend setup/run instructions must be supplied by Executor 1; no backend source, dependency manifest, or run guide was present in the folder. Do not derive an algorithm or backend command from the raw workbooks.

## Known limitations and assumptions

- API schema above is the frontend's explicit provisional contract, not a discovered backend contract. Reconcile it with Executor 1 before integration.
- The frontend treats a successful 2xx approval response as accepted. The backend must enforce authorization and persist the approval audit record.
- The CSV headers are a documented provisional 1C mapping, not verified against a provided partner import template.
- PII filtering detects common email/phone/contact indicators. Backend data should be anonymized at source and reviewed against the contract; heuristic checks cannot guarantee detection of every sensitive value.
- Stock trends in this UI show backend-provided current stock, monthly use and lead time; the demo does not construct historical trend series.
- Authentication/authorization and supplier dispatch are outside this frontend; the backend must authorize approvals and validate/anonymize uploaded reports.
- The supplied source folder had workbooks but no API service, backend technical write-up, or 1C interface specification.
