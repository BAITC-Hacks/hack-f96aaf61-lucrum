from datetime import date
import csv
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.engine import Dataset, Product, SalesMonth, Stock, Supplier


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Use deterministic in-memory data; tests never parse partner workbooks."""
    dataset = Dataset(
        sales=[
            SalesMonth(date(2025, month, 1), "SKU-A", "WH-1", 40, None)
            for month in range(1, 13)
        ] + [
            SalesMonth(date(2025, month, 1), "SKU-B", "WH-2", 25, None)
            for month in range(1, 13)
        ],
        stock=[Stock("SKU-A", "WH-1", 0), Stock("SKU-B", "WH-2", 0)],
        suppliers=[
            Supplier("SKU-A", "SUP-A", "Supplier A", 30),
            Supplier("SKU-B", "SUP-B", "Supplier B", 30),
        ],
        products=[
            Product("SKU-A", "Product A", "lighting"),
            Product("SKU-B", "Product B", "cables"),
        ],
    )
    monkeypatch.setattr("backend.app.load_dataset", lambda _path, fallback_on_error=True: dataset)
    monkeypatch.setenv("LUCRUM_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("LUCRUM_DB_PATH", str(tmp_path / "orders.sqlite3"))
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "api_version": "v1"}


def test_calculate_endpoint_returns_v1_explained_orders(client):
    response = client.post("/api/calculate")
    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == "v1"
    assert {item["sku"] for item in body["orders"]} == {"SKU-A", "SKU-B"}
    assert all(item["quantity"] > 0 and item["justification"] for item in body["orders"])


def test_calculate_filters_by_warehouse_and_category(client):
    by_warehouse = client.post("/api/calculate?warehouse=WH-1").json()
    assert by_warehouse["api_version"] == "v1"
    assert {row["warehouse"] for row in by_warehouse["orders"]} == {"WH-1"}

    by_category = client.post("/api/calculate?category=cables").json()
    assert {row["sku"] for row in by_category["orders"]} == {"SKU-B"}


def test_orders_endpoint_groups_latest_calculation_by_supplier(client):
    assert client.post("/api/calculate").status_code == 200
    response = client.get("/api/orders")
    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == "v1"
    assert {supplier["supplier_code"] for supplier in body["suppliers"]} == {"SUP-A", "SUP-B"}
    assert all(supplier["items"] for supplier in body["suppliers"])


def test_stock_endpoint_and_warehouse_filter(client):
    response = client.get("/api/stock")
    assert response.status_code == 200
    assert response.json()["api_version"] == "v1"
    assert len(response.json()["items"]) == 2

    filtered = client.get("/api/stock?warehouse=WH-2").json()
    assert {row["warehouse"] for row in filtered["items"]} == {"WH-2"}
    assert all(row["stockout"] for row in filtered["items"])


def test_approval_requires_confirmation_and_can_target_supplier(client):
    calculation = client.post("/api/calculate").json()
    assert len(calculation["orders"]) == 2

    rejected = client.post("/api/orders/approve", json={"supplier_codes": ["SUP-A"]})
    assert rejected.status_code == 400

    response = client.post("/api/orders/approve", json={
        "supplier_codes": ["SUP-A"], "confirmed": True, "manager_note": "Reviewed by manager",
        "approved_by": "manager-17",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == "v1"
    assert len(body["approved"]) == 1
    assert body["status"] == "approved"
    assert body["approval_timestamp"]
    approved_item_id = body["approved"][0]
    assert body["approval_timestamps"][approved_item_id] == body["approval_timestamp"]

    rows = client.get("/api/orders").json()["suppliers"]
    item = next(group["items"][0] for group in rows if group["supplier_code"] == "SUP-A")
    assert item["status"] == "approved"
    assert item["approval_timestamp"]
    assert item["manager_note"] == "Reviewed by manager"
    assert item["approved_by"] == "manager-17"
    assert item["approved_at"] == item["approval_timestamp"]

    repeated = client.post("/api/orders/approve", json={
        "item_ids": [item["id"]], "confirmed": True
    })
    assert repeated.status_code == 200
    assert repeated.json()["message"] == "Item is already approved"
    assert repeated.json()["already_approved"] == [item["id"]]
    assert repeated.json()["approval_timestamp"] == body["approval_timestamp"]
    assert repeated.json()["approval_timestamps"][item["id"]] == body["approval_timestamp"]
    assert repeated.json()["approved"] == []
    assert repeated.json()["approved_by"] == "manager-17"
    assert repeated.json()["approval_actors"][item["id"]] == "manager-17"


def test_1c_export_contains_only_approved_items(client):
    client.post("/api/calculate")
    orders = client.get("/api/orders").json()["suppliers"]
    first_item = orders[0]["items"][0]
    approval = client.post("/api/orders/approve", json={
        "item_ids": [first_item["id"]], "confirmed": True
    })
    assert approval.status_code == 200
    assert approval.json()["approved"] == [first_item["id"]]

    approval_date = approval.json()["approval_timestamp"][:10]
    response = client.get(
        f"/api/orders/export-1c?date={approval_date}&supplier_code={first_item['supplier_code']}&warehouse={first_item['warehouse']}"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.splitlines()
    assert lines[0] == "SupplierCode,SKU,Quantity,Warehouse"
    assert len(lines) == 2
    export_row = next(csv.DictReader(lines))
    assert export_row == {
        "SupplierCode": first_item["supplier_code"], "SKU": first_item["sku"],
        "Quantity": str(first_item["quantity"]), "Warehouse": first_item["warehouse"],
    }

    unmatched = client.get("/api/orders/export-1c?supplier_code=NO-SUCH-SUPPLIER")
    assert unmatched.status_code == 404
    assert unmatched.json()["detail"] == "No approved positions found for export"


def test_export_without_approvals_returns_not_found(client):
    client.post("/api/calculate")
    response = client.get("/api/orders/export-1c")
    assert response.status_code == 404
    assert response.json()["detail"] == "No approved positions found for export"


def test_upload_xlsx_reloads_dataset_and_stores_safe_filename(client, tmp_path):
    workbook = BytesIO()
    with ZipFile(workbook, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    response = client.post("/api/upload", files={
        "file": ("sales report.xlsx", workbook.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    })
    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == "v1"
    assert body["reloaded"] is True
    assert body["filename"].endswith(".xlsx")
    assert (tmp_path / "raw" / body["filename"]).is_file()
    assert body["counts"]["sales"] == 24


def test_upload_rejects_non_xlsx_files(client):
    response = client.post("/api/upload", files={"file": ("report.csv", b"data", "text/csv")})
    assert response.status_code == 400
