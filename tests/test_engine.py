from datetime import date

from backend.engine import (BomLine, Dataset, Product, SalesMonth, Stock, Stockout,
                            Supplier, Transit, calculate, grouped_orders)


def sample() -> Dataset:
    sales = [SalesMonth(date(2025, m, 1), "P", "W", 10, f"CLIENT_{m:03}")
             for m in range(1, 13)]
    return Dataset(sales=sales, stock=[Stock("P", "W", 0)],
                   suppliers=[Supplier("P", "S", "Supplier", 30)],
                   products=[Product("P", "Product", "cat")])


def test_transit_reduces_recommendation_and_orders_group_by_supplier():
    data = sample()
    before = calculate(data)["orders"][0]["quantity"]
    data.transit = [Transit("P", "W", 5)]
    after = calculate(data)["orders"][0]["quantity"]
    assert after == before - 5
    assert grouped_orders(calculate(data))["suppliers"][0]["items"][0]["justification"]


def test_bom_component_receives_parent_assembly_demand():
    data = sample()
    data.bom = [BomLine("P", "C", 2)]
    data.suppliers.append(Supplier("C", "S2", "Parts", 30))
    data.products.append(Product("C", "Component", "cat"))
    assert any(row["sku"] == "C" for row in calculate(data)["orders"])


def test_stockout_is_compensated_and_reported():
    data = sample()
    data.sales = [SalesMonth(date(2025, m, 1), "P", "W", 10 if m != 12 else 0,
                             f"CLIENT_{m:03}") for m in range(1, 13)]
    data.stockouts = [Stockout("P", "W", date(2025, 12, 1), date(2025, 12, 31))]
    row = calculate(data)["orders"][0]
    assert row["forecast_monthly_demand"] > 0
    assert any("Stockout months compensated" in reason for reason in row["justification"])


def test_outputs_retain_explanation_and_codes():
    row = calculate(sample())["orders"][0]
    assert row["sku"] == "P" and row["supplier_code"] == "S"
    assert row["justification"]


def test_seasonality_changes_forecast_from_plain_recent_average():
    data = sample()
    data.sales = [SalesMonth(date(y, m, 1), "P", "W", 100 if m == 1 else 10,
                             None)
                  for y in (2024, 2025) for m in range(1, 13)]
    seasonal_row = calculate(data)["orders"][0]
    seasonal = seasonal_row["forecast_monthly_demand"]
    data.sales = [SalesMonth(date(y, m, 1), "P", "W", 10, None)
                  for y in (2024, 2025) for m in range(1, 13)]
    flat = calculate(data)["orders"][0]["forecast_monthly_demand"]
    assert seasonal > flat
    assert any("Seasonality factor" in reason for reason in seasonal_row["justification"])


def test_single_client_bulk_purchase_does_not_distort_regular_forecast():
    data = sample()
    base = calculate(data)["orders"][0]["forecast_monthly_demand"]
    data.sales.append(SalesMonth(date(2025, 12, 1), "P", "W", 500, "CLIENT_BULK"))
    with_bulk = calculate(data)["orders"][0]
    assert with_bulk["forecast_monthly_demand"] == base
    assert any("anomalous" in reason for reason in with_bulk["justification"])
