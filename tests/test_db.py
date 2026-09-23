from backend.db import OrderDatabase


def test_export_mapping_uses_real_supplier_name_when_code_is_unknown(tmp_path):
    database = OrderDatabase(tmp_path / "recommendations.sqlite3")
    order = {
        "sku": "SKU-1",
        "product_name": "Test product",
        "category": "test",
        "warehouse": "WH-1",
        "unit": "pcs",
        "supplier_code": "Unknown supplier",
        "supplier_name": "Real Vendor Name",
        "quantity": 3,
        "forecast_monthly_demand": 3.0,
        "urgency": "normal",
        "justification": ["test"],
    }
    saved = database.save_calculation([order])
    item_id = saved["orders"][0]["id"]
    approved = database.approve([item_id], [], approved_by="manager-1")

    assert approved["approved"] == [item_id]
    assert database.approved_latest()[0]["supplier_code"] == "Real Vendor Name"
