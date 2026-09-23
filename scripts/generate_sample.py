"""Create deterministic, non-personal sample CSVs under data/sample."""
import csv
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "sample"
OUT.mkdir(parents=True, exist_ok=True)

with (OUT / "sales.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["month", "sku", "warehouse", "quantity", "client_id"])
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            seasonal = 2.0 if month in (11, 12) else 1.0
            qty = round(12 * seasonal * (1 + 0.05 * (year - 2024)))
            w.writerow([date(year, month, 1).isoformat(), "SAMPLE-LAMP", "SAMPLE-WH", qty, "CLIENT_SAMPLE_001"])
    w.writerow(["2025-12-01", "SAMPLE-LAMP", "SAMPLE-WH", 300, "CLIENT_SAMPLE_BULK"])

for name, header, rows in [
    ("stock.csv", ["sku", "warehouse", "quantity"], [["SAMPLE-LAMP", "SAMPLE-WH", 8]]),
    ("in_transit.csv", ["sku", "warehouse", "quantity"], [["SAMPLE-LAMP", "SAMPLE-WH", 4]]),
    ("suppliers.csv", ["sku", "supplier_code", "supplier_name", "lead_time_days", "moq"], [["SAMPLE-LAMP", "SAMPLE-SUP", "Sample supplier", 21, 1]]),
    ("products.csv", ["sku", "name", "category", "unit"], [["SAMPLE-LAMP", "Sample lamp", "lighting", "pcs"]]),
    ("stockouts.csv", ["sku", "warehouse", "start", "end"], [["SAMPLE-LAMP", "SAMPLE-WH", "2025-07-01", "2025-07-31"]]),
    ("bom.csv", ["parent_sku", "component_sku", "quantity"], [["SAMPLE-LAMP", "SAMPLE-DRIVER", 1]]),
]:
    with (OUT / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)
