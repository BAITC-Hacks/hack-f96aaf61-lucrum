# Lucrum

Hackathon project for automated supplier order recommendations for Elektrokomplekt LLP. The service is intended to help a procurement manager review replenishment proposals. It must not place or send orders automatically; a responsible employee must approve them.

## Source workbooks (`data/raw/`)

The supplied Excel files are in `data/raw/`. Their names indicate these source roles:

| Workbook(s) | Data needed from it |
| --- | --- |
| `Ежемесячные продажи в количественном выражении за последние 2 года (2).xlsx`, `Ежемесячные продажи в кол-м выражении SystemElectric 2024-2026 (2).xlsx` | Historical monthly sales by item, for the ИЭК and SystemElectric ranges |
| `Динамика продаж_2025-2026 (2).xlsx`, `Динамика продаж_Syseme Electric_2025-2026 (2).xlsx` | Sales dynamics detail; use to clarify or supplement the monthly series where its item/date/quantity grain is needed |
| `Ежемесячные остатки продукции за последние 2 года  ИЭК (2).xlsx`, `Ежемесячные остатки SystemElectric 2024-2026 (2).xlsx` | Historical stock by item and month; useful for identifying stockout periods and demand censored by zero stock |
| `Товар в пути_SystemElectric на 22.09.2026 (2).xlsx`, `Путь ИЭК 22.09.2026 (2).xlsx` | Goods in transit by product; latest snapshot dated 22 September 2026 |
| `MOQ  ИЭК (2).xlsx`, `MOQ SystemElectric (2).xlsx` | Product/supplier minimum order quantities and supplier terms, where included |
| `Сезонность ИЭК (2).xlsx`, `Сезонность SystemElectric 2024-2026 (2).xlsx` | Seasonal analysis/reports; the calculation can also estimate seasonal pattern from the underlying monthly sales history |

These filenames identify the sources, but their worksheet names, headers, and field meanings still need to be mapped. To calculate reliable recommendations, the normalized records need:

| Data | Required fields |
| --- | --- |
| Sales | Month/date, SKU/article code, quantity, warehouse (if applicable); anonymized client token if transaction-level client attribution exists |
| Stock | SKU/article code, warehouse, quantity and snapshot date; historical monthly stock is especially useful for stockout compensation |
| Goods in transit | SKU/article code, destination warehouse, open quantity; delivery dates/status if available |
| Supplier terms | SKU/article code, supplier code/name, lead time in days, MOQ if applicable |
| Products | SKU/article code, product name, category, unit of measure |
| Stockouts | SKU/article code, warehouse, start and end dates (can be derived from dated stock records when reliable) |
| BOM | Parent/product SKU, component SKU, component quantity and unit; retain the matching 1C item codes |

The listed workbooks provide sales, stock, transit, MOQ, and seasonality-related sources. A supplier lead-time directory, product/category mapping, and 1C BOM were not identifiable by filename in the supplied set; add them if they are separate files. If supplier or BOM fields are embedded in an existing workbook, record the worksheet and columns that contain them. Preserve source workbooks unchanged and do not add temporary exports or synthetic examples to `data/raw/`.

### Column and data requirements

- Use one row per sales transaction line. Sales history should cover as much history as possible (ideally at least two years to capture seasonality). Include zero-sales/stock availability history if you have it; sales alone cannot reliably distinguish low demand from a stockout.
- Quantities should be numeric and consistently expressed in the product's unit of measure. Dates should be actual Excel dates or unambiguous dates such as `YYYY-MM-DD`.
- Use the same SKU/article code and warehouse identifier consistently across all workbooks. Include supplier and 1C codes where available; names alone may not uniquely identify records.
- Stock and in-transit quantities should represent the latest known snapshot/status. Mark cancelled or closed purchase orders so they are not counted as incoming supply.
- Client identifiers must already be anonymized (for example, stable generated tokens such as `CLIENT_000123`). Do not include customer names, phone numbers, addresses, email addresses, or other personally identifiable information.
- If an optional field is not available, leave it blank rather than inventing data. Keep units, currencies, and the meaning of each quantity documented.

### Privacy and mapping

- Use the same SKU/article code and warehouse identifier across sources; include supplier and 1C codes where available. Document units, currencies, date semantics, and whether monthly quantities mean sales or closing stock.
- Client identifiers must be anonymized tokens (for example, `CLIENT_000123`). Do not include customer names, phone numbers, addresses, emails, or other personally identifiable information.
- Do not commit confidential partner XLSX files to a public repository. These source files are local inputs; use an approved private location and keep only anonymized or synthetic data in shared examples.
- Workbook sheets and header rows are inspected dynamically. The loader selects recognized columns only and never imports client/contact identifiers; it aggregates sales monthly, derives stockout intervals from zero-stock months, and uses the monthly sales series to estimate seasonality rather than treating a seasonality report as additional sales. If monthly sales books exist, similarly named sales-dynamics books are not added to avoid duplicate counting. Unusual source headers may need aliases added. Missing lead times are logged and defaulted to 30 days; missing product categories remain `uncategorized`. See [API contract](docs/API.md) and [sample data](data/sample/README.md).

## Backend

Install dependencies with `pip install -r requirements.txt`, then run `uvicorn backend.app:app --reload`. At startup the service loads recognized workbooks from `data/raw/`; set `LUCRUM_RAW_DIR` to use another directory. `POST /api/upload` accepts `.xlsx` reports up to 25 MiB and reloads the dataset after a successful parse. If inputs are missing or malformed, it logs a warning and serves the deterministic synthetic sample dataset. SQLite persistence defaults to `data/lucrum.sqlite3`; set `LUCRUM_DB_PATH` to change it. Recommendations remain pending until explicitly approved through the API; approved rows can be downloaded as a 1C-compatible CSV. Replenishment formulas and assumptions are described in [backend methodology](docs/METHODOLOGY.md). Synthetic CSV examples can be generated with `python scripts/generate_sample.py`.
