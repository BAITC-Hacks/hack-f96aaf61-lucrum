import pandas as pd

from backend import loader


def test_read_sheets_finds_header_on_second_row(monkeypatch, tmp_path):
    class Workbook:
        sheet_names = ["Sales"]

        def parse(self, sheet_name, header=0, nrows=None, usecols=None):
            if nrows == 0:
                columns = ["Количество"] if header == 0 else ["Артикул", "Количество"]
                return pd.DataFrame(columns=columns)
            frame = pd.DataFrame({"Артикул": ["SKU-1"], "Количество": [12]})
            return frame.loc[:, [col for col in frame.columns if usecols(col)]]

    monkeypatch.setattr(loader.pd, "ExcelFile", lambda *args, **kwargs: Workbook())
    frames = loader._read_sheets(tmp_path / "sales.xlsx")
    assert len(frames) == 1
    assert list(frames[0].columns) == ["Артикул", "Количество"]


def test_short_unrecognized_sheet_fails_over_to_synthetic(monkeypatch, tmp_path):
    workbook = tmp_path / "sales.xlsx"
    workbook.touch()

    class ShortWorkbook:
        sheet_names = ["Short"]

        def parse(self, sheet_name, header=0, nrows=None, usecols=None):
            if header > 1:
                raise ValueError("header row exceeds sheet length")
            return pd.DataFrame(columns=["Заголовок"])

    monkeypatch.setattr(loader.pd, "ExcelFile", lambda *args, **kwargs: ShortWorkbook())
    dataset = loader.load_dataset(tmp_path)
    assert dataset.sales
    assert dataset.sales[0].sku == "SAMPLE-LAMP"
    assert all(row.client_id and row.client_id.startswith("SYNTHETIC_") for row in dataset.sales)


def test_missing_directory_returns_synthetic_sample(tmp_path):
    dataset = loader.load_dataset(tmp_path / "missing")
    assert dataset.sales
    assert dataset.stock
    assert dataset.transit


def test_supplier_directory_maps_real_supplier_to_sales_sku(monkeypatch, tmp_path):
    sales_path = tmp_path / "sales.xlsx"
    supplier_path = tmp_path / "nomenclature.xlsx"
    sales_path.touch()
    supplier_path.touch()
    frames = {
        sales_path.name: [pd.DataFrame({
            "Артикул": ["SKU-1"], "Период": ["2025-01-01"], "Количество": [12],
        })],
        supplier_path.name: [pd.DataFrame({
            "Артикул": ["SKU-1"], "Поставщик": ["Real Vendor"], "Код поставщика": ["SUP-42"],
        })],
    }
    monkeypatch.setattr(loader, "_read_sheets", lambda path, require_sku=True: frames[path.name])
    monkeypatch.setattr(loader, "_role_from_headers", lambda path: "moq")

    dataset = loader._load_dataset(tmp_path, fallback_on_error=False)

    assert [(supplier.sku, supplier.supplier_code, supplier.supplier_name)
            for supplier in dataset.suppliers] == [("SKU-1", "SUP-42", "Real Vendor")]


def test_nomenclature_code_is_used_instead_of_product_description():
    frame = pd.DataFrame({
        "Номенклатура": ["Product description"],
        "Номенклатура.Код": ["SKU-1"],
    })

    assert loader._column(frame, loader._SKU) == "Номенклатура.Код"


def test_internal_1c_code_precedes_supplier_article_and_transit_headers_are_recognized():
    frame = pd.DataFrame(columns=[
        "Артикул поставщика", "Код 1С", "Поступление до 2026-10-10", "Товар в пути",
    ])

    assert loader._column(frame, loader._SKU) == "Код 1С"
    assert {column for column in frame.columns
            if any(alias in loader._norm(column) for alias in loader._TRANSIT_QTY)} == {
        "Поступление до 2026-10-10", "Товар в пути",
    }
