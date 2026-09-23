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
