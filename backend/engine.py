"""Explainable monthly demand forecasting and supplier replenishment."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from math import ceil
from statistics import median


@dataclass(frozen=True)
class SalesMonth:
    month: date  # first day of month
    sku: str
    warehouse: str
    quantity: float
    client_id: str | None = None  # anonymized token only


@dataclass(frozen=True)
class Stock:
    sku: str
    warehouse: str
    quantity: float


@dataclass(frozen=True)
class Transit:
    sku: str
    warehouse: str
    quantity: float


@dataclass(frozen=True)
class Supplier:
    sku: str
    supplier_code: str
    supplier_name: str
    lead_time_days: int
    moq: float = 0


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    category: str = "uncategorized"
    unit: str = "pcs"


@dataclass(frozen=True)
class Stockout:
    sku: str
    warehouse: str
    start: date
    end: date


@dataclass(frozen=True)
class BomLine:
    parent_sku: str
    component_sku: str
    quantity: float


@dataclass
class Dataset:
    sales: list[SalesMonth] = field(default_factory=list)
    stock: list[Stock] = field(default_factory=list)
    transit: list[Transit] = field(default_factory=list)
    suppliers: list[Supplier] = field(default_factory=list)
    products: list[Product] = field(default_factory=list)
    stockouts: list[Stockout] = field(default_factory=list)
    bom: list[BomLine] = field(default_factory=list)


def _robust_sales(rows: list[SalesMonth]) -> tuple[list[SalesMonth], list[str]]:
    """Winsorize monthly spikes; remove client-month purchases > 4x SKU median."""
    regular = [r for r in rows if r.quantity >= 0]
    notes: list[str] = []
    by_sku: dict[str, list[float]] = defaultdict(list)
    by_client: dict[tuple[str, str], float] = defaultdict(float)
    for r in regular:
        by_sku[r.sku].append(r.quantity)
        if r.client_id:
            by_client[(r.sku, r.client_id)] += r.quantity
    thresholds = {sku: max(1.0, median(v) * 4) for sku, v in by_sku.items()}
    bulk_clients = {(sku, client) for (sku, client), qty in by_client.items()
                    if qty > thresholds.get(sku, float("inf"))}
    if bulk_clients:
        notes.append(f"Excluded {len(bulk_clients)} anomalous SKU/client purchase group(s).")
    filtered = [r for r in regular if not r.client_id or (r.sku, r.client_id) not in bulk_clients]
    return filtered, notes


def _seasonal_forecast(values: dict[date, float], stockouts: list[Stockout], sku: str,
                       warehouse: str) -> tuple[float, list[str]]:
    if not values:
        return 0.0, ["No sales history; forecast is zero."]
    ordered = sorted(values.items())
    notes: list[str] = []
    corrected = dict(values)
    for so in stockouts:
        if so.sku != sku or so.warehouse != warehouse:
            continue
        for month in list(corrected):
            if so.start <= month <= so.end:
                prior = [q for d, q in ordered if d < month and q > 0]
                if prior:
                    corrected[month] = max(corrected[month], median(prior[-6:]))
        notes.append("Stockout months compensated using recent median demand.")
    vals = list(corrected.values())
    base = sum(vals[-6:]) / min(6, len(vals))
    # Recent-vs-prior trend capped to avoid unstable extrapolation.
    if len(vals) >= 12:
        recent = sum(vals[-6:]) / 6
        prior = sum(vals[-12:-6]) / 6
        growth = max(-0.25, min(0.25, recent / prior - 1 if prior else 0))
        base *= 1 + growth
        if abs(growth) >= 0.03:
            notes.append(f"Recent trend adjustment: {growth:+.0%}.")
    # Seasonal factor from same-month observations, blended toward neutral.
    target_month = (ordered[-1][0].month % 12) + 1
    same = [q for d, q in corrected.items() if d.month == target_month]
    overall = sum(vals) / len(vals)
    if len(same) >= 2 and overall > 0:
        factor = sum(same) / len(same) / overall
        factor = max(0.5, min(1.8, factor))
        base *= 0.5 + factor * 0.5
        notes.append(f"Seasonality factor: {factor:.2f}.")
    return max(0.0, base), notes


def calculate(data: Dataset, warehouse: str | None = None,
              category: str | None = None) -> dict:
    """Return contract v1 recommendations; no external order action is performed."""
    clean_sales, anomaly_notes = _robust_sales(data.sales)
    products = {p.sku: p for p in data.products}
    stock = {(r.sku, r.warehouse): r.quantity for r in data.stock}
    transit: dict[tuple[str, str], float] = defaultdict(float)
    for r in data.transit:
        transit[(r.sku, r.warehouse)] += r.quantity
    suppliers = {s.sku: s for s in data.suppliers}
    groups: dict[tuple[str, str], dict[date, float]] = defaultdict(lambda: defaultdict(float))
    bom_by_parent: dict[str, list[BomLine]] = defaultdict(list)
    for line in data.bom:
        bom_by_parent[line.parent_sku].append(line)
    for r in clean_sales:
        if warehouse and r.warehouse != warehouse:
            continue
        groups[(r.sku, r.warehouse)][r.month] += r.quantity
        # Convert sold parent assemblies into component-equivalent demand.
        for line in bom_by_parent.get(r.sku, []):
            groups[(line.component_sku, r.warehouse)][r.month] += r.quantity * line.quantity
    rows = []
    for (sku, wh), values in groups.items():
        product = products.get(sku, Product(sku, sku))
        if category and product.category != category:
            continue
        supplier = suppliers.get(sku)
        if not supplier:
            continue
        forecast, why = _seasonal_forecast(values, data.stockouts, sku, wh)
        lead_demand = forecast * supplier.lead_time_days / 30
        on_hand = stock.get((sku, wh), 0.0)
        incoming = transit.get((sku, wh), 0.0)
        qty = max(0.0, ceil(lead_demand - on_hand - incoming))
        if qty and supplier.moq:
            qty = max(qty, ceil(supplier.moq))
            why.append(f"Supplier MOQ applied: {supplier.moq:g} {product.unit}.")
        if qty == 0:
            continue
        why.extend(anomaly_notes)
        why += [f"Forecast demand: {forecast:.2f} {product.unit}/month.",
                f"Lead time: {supplier.lead_time_days} days; on hand {on_hand:g}; incoming {incoming:g}."]
        rows.append({"sku": sku, "product_name": product.name, "category": product.category,
                     "warehouse": wh, "unit": product.unit, "supplier_code": supplier.supplier_code,
                     "supplier_name": supplier.supplier_name, "quantity": qty,
                     "forecast_monthly_demand": round(forecast, 2),
                     "urgency": "high" if on_hand <= forecast * supplier.lead_time_days / 30 else "normal",
                     "justification": why})
    return {"api_version": "v1", "orders": rows}


def stock_status(data: Dataset, warehouse: str | None = None) -> dict:
    return {"api_version": "v1", "items": [
        {"sku": r.sku, "warehouse": r.warehouse, "quantity": r.quantity,
         "stockout": r.quantity <= 0}
        for r in data.stock if warehouse is None or r.warehouse == warehouse]}


def grouped_orders(result: dict) -> dict:
    groups: dict[str, list] = defaultdict(list)
    for row in result["orders"]:
        groups[row["supplier_code"]].append(row)
    return {"api_version": "v1", "suppliers": [
        {"supplier_code": code, "supplier_name": rows[0]["supplier_name"], "items": rows}
        for code, rows in sorted(groups.items())]}
