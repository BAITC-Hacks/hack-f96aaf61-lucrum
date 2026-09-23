"""Best-effort structural adapter for the partner XLSX exports.

The exports have several layouts and are not allowed to define arbitrary fields:
only explicitly recognized SKU, date/month, quantity, warehouse, category,
supplier, and MOQ columns are read. Client/contact columns are never imported.
"""
from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .engine import BomLine, Dataset, Product, SalesMonth, Stock, Stockout, Supplier, Transit

logger = logging.getLogger(__name__)

_SKU = ("sku", "артикул", "код товара", "код номенклатуры", "номенклатурный номер",
        "код продукции", "код позиции", "номенклатура", "код")
_NAME = ("наименование", "название товара", "продукт", "товар", "номенклатура", "name")
_QTY = ("количество", "кол-во", "объем", "объём", "остаток", "в пути", "quantity", "qty", "stock")
_DATE = ("дата", "период", "месяц", "date", "month", "period")
_WAREHOUSE = ("склад", "warehouse", "филиал", "регион")
_CATEGORY = ("категория", "группа товара", "товарная группа", "category")
_SUPPLIER = ("поставщик", "supplier")
_SUPPLIER_CODE = ("код поставщика", "supplier code", "supplier_code")
_LEAD = ("срок поставки", "срок поставки дней", "lead time", "lead_time")
_MOQ = ("moq", "мин заказ", "минимальный заказ", "минимальная партия", "кратность")
_SENSITIVE = ("клиент", "покупатель", "customer", "client", "фио", "фамилия", "имя клиента",
              "телефон", "phone", "email", "e-mail", "электронная почта", "адрес", "паспорт",
              "контактное лицо", "контрагент")


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower().replace("ё", "е"))


def _column(frame: pd.DataFrame, aliases: tuple[str, ...]) -> Any | None:
    for alias in sorted(aliases, key=len, reverse=True):
        for col in frame.columns:
            label = _norm(col)
            is_code_label = any(marker in label for marker in ("код", "артикул", "sku"))
            if (alias in label and not any(marker in label for marker in _SENSITIVE)
                    and not (aliases is _NAME and is_code_label)):
                return col
    return None


def _safe_header(label: Any) -> bool:
    normalized = _norm(label)
    if any(marker in normalized for marker in _SENSITIVE):
        return False
    aliases = _SKU + _NAME + _QTY + _DATE + _WAREHOUSE + _CATEGORY + _SUPPLIER + _SUPPLIER_CODE + _LEAD + _MOQ
    return any(alias in normalized for alias in aliases) or _month(label) is not None


def _month(value: Any) -> date | None:
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return date(value.year, value.month, 1)
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    ru_months = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "мая": 5,
                 "май": 5, "июн": 6, "июл": 7, "август": 8, "сентябр": 9,
                 "октябр": 10, "ноябр": 11, "декабр": 12}
    year_match = re.search(r"20\d{2}", text)
    if year_match:
        lowered = _norm(text)
        for month_text, month_num in ru_months.items():
            if month_text in lowered:
                return date(int(year_match.group()), month_num, 1)
    # Column headings such as 2024-01, 01.2024, or Jan-2024.
    try:
        parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
        if not pd.isna(parsed):
            return date(parsed.year, parsed.month, 1)
    except (ValueError, TypeError, OverflowError):
        pass
    match = re.search(r"(?<!\d)(0?[1-9]|1[0-2])[.\-/ ](20\d{2})(?!\d)", text)
    if match:
        return date(int(match.group(2)), int(match.group(1)), 1)
    match = re.search(r"(20\d{2})[.\-/ ](0?[1-9]|1[0-2])", text)
    if match:
        return date(int(match.group(1)), int(match.group(2)), 1)
    return None


def _number(value: Any) -> float | None:
    if pd.isna(value):
        return None
    if isinstance(value, str):
        value = value.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _text(value: Any, fallback: str = "") -> str:
    if pd.isna(value):
        return fallback
    return str(value).strip()


def _read_sheets(path: Path, require_sku: bool = True) -> list[pd.DataFrame]:
    """Read recognized columns only, so client/contact values never enter frames."""
    book = pd.ExcelFile(path, engine="openpyxl")
    result: list[pd.DataFrame] = []
    for sheet in book.sheet_names:
        # Scan only header metadata, never rows containing customer data.
        header_row = None
        for candidate in range(6):
            try:
                headers = book.parse(sheet_name=sheet, header=candidate, nrows=0)
            except (ValueError, IndexError) as exc:
                logger.warning("Header scan stopped for %s sheet %s at row %d: %s",
                               path.name, sheet, candidate, exc)
                break
            if _column(headers, _SKU) is not None:
                header_row = candidate
                break
        if header_row is None:
            logger.warning("Skipping %s sheet %s without recognizable SKU headers.", path.name, sheet)
            continue
        try:
            frame = book.parse(sheet_name=sheet, header=header_row, usecols=_safe_header)
        except (ValueError, IndexError, KeyError) as exc:
            raise ValueError(f"Could not parse {path.name}, sheet {sheet!r}, header row {header_row}: {exc}") from exc
        frame = frame.dropna(how="all")
        if not frame.empty:
            result.append(frame)
    if book.sheet_names and not result and require_sku:
        raise ValueError(f"No sheets with recognizable SKU headers found in {path.name}")
    return result


def synthetic_dataset() -> Dataset:
    """Small deterministic, explicitly synthetic fallback with no real client data."""
    dataset = Dataset(
        stock=[Stock("SAMPLE-LAMP", "SAMPLE-WH", 8)],
        transit=[Transit("SAMPLE-LAMP", "SAMPLE-WH", 4)],
        suppliers=[Supplier("SAMPLE-LAMP", "SAMPLE-SUP", "Sample supplier", 21, 1)],
        products=[Product("SAMPLE-LAMP", "Sample lamp", "lighting", "pcs")],
        stockouts=[Stockout("SAMPLE-LAMP", "SAMPLE-WH", date(2025, 7, 1), date(2025, 7, 31))],
        bom=[BomLine("SAMPLE-LAMP", "SAMPLE-DRIVER", 1)],
    )
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            if year == 2026 and month > 9:
                continue
            seasonal = 2 if month in (11, 12) else 1
            quantity = round(12 * seasonal * (1 + 0.05 * (year - 2024)))
            dataset.sales.append(SalesMonth(date(year, month, 1), "SAMPLE-LAMP", "SAMPLE-WH",
                                            quantity, f"SYNTHETIC_CLIENT_{year}_{month:02}"))
    # Deliberate synthetic single-client spike exercises anomaly filtering.
    dataset.sales.append(SalesMonth(date(2025, 12, 1), "SAMPLE-LAMP", "SAMPLE-WH",
                                    300, "SYNTHETIC_CLIENT_BULK"))
    dataset.products.append(Product("SAMPLE-DRIVER", "Sample driver", "lighting", "pcs"))
    dataset.suppliers.append(Supplier("SAMPLE-DRIVER", "SAMPLE-SUP", "Sample supplier", 21, 1))
    return dataset


def _role(path: Path) -> str | None:
    name = _norm(path.stem)
    if "moq" in name or "минимальн" in name:
        return "moq"
    if "в пути" in name or "путь" in name or "transit" in name:
        return "transit"
    if "остатк" in name or "stock" in name:
        return "stock"
    if "динамик" in name:
        return "sales_detail"
    if "продаж" in name or "sales" in name:
        return "sales"
    if "сезонност" in name or "season" in name:
        return "seasonality"
    return None


def _role_from_headers(path: Path) -> str | None:
    """Infer a workbook's data role from header metadata when its name is generic."""
    book = pd.ExcelFile(path, engine="openpyxl")
    for sheet in book.sheet_names:
        for candidate in range(6):
            try:
                headers = book.parse(sheet_name=sheet, header=candidate, nrows=0)
            except (ValueError, IndexError):
                break
            if _column(headers, _SKU) is None:
                continue
            labels = [_norm(column) for column in headers.columns]
            joined = " ".join(labels)
            if _column(headers, _MOQ) is not None or (
                _column(headers, _SUPPLIER) is not None and _column(headers, _LEAD) is not None
            ):
                return "moq"
            if any(token in joined for token in ("в пути", "in transit", "transit", "ожидаемая поставка")):
                return "transit"
            if _column(headers, _QTY) is not None and any(token in joined for token in ("остаток", "stock", "наличие")):
                return "stock"
            if _column(headers, _DATE) is not None or any(_month(label) for label in labels):
                return "sales"
            if any(token in joined for token in ("сезонность", "seasonality")):
                return "seasonality"
    return None


def _load_dataset(raw_dir: str | Path, fallback_on_error: bool = True) -> Dataset:
    """Load recognized partner XLSX files, returning empty Dataset if none exist.

    Parsing errors for present workbooks are raised with their filename instead
    of being swallowed. Ambiguous/unrecognized sheets are skipped with a log
    message. This adapter does not import client names, contacts, or raw client
    IDs; SalesMonth.client_id remains None.
    """
    root = Path(raw_dir)
    paths = sorted(root.glob("*.xlsx")) if root.is_dir() else []
    if not paths:
        if not fallback_on_error:
            raise ValueError(f"No XLSX inputs found in {root}")
        logger.warning("No XLSX inputs found in %s; using synthetic sample data.", root)
        return synthetic_dataset()
    frames: dict[str, list[pd.DataFrame]] = defaultdict(list)
    for path in paths:
        role = _role(path)
        if role is None:
            try:
                role = _role_from_headers(path)
            except Exception as exc:
                if not fallback_on_error:
                    raise ValueError(f"Unable to inspect workbook {path.name}: {type(exc).__name__}") from exc
                logger.warning("Unable to inspect workbook %s; skipping it.", path.name)
        if role is None:
            if not fallback_on_error:
                raise ValueError(f"Could not identify workbook data type: {path.name}")
            logger.warning("Skipping unrecognized workbook: %s", path.name)
            continue
        try:
            frames[role].extend(_read_sheets(path, require_sku=role != "seasonality"))
        except Exception as exc:
            logger.warning("Unable to parse workbook %s (%s: %s); using synthetic sample data.",
                           path.name, type(exc).__name__, exc)
            if not fallback_on_error:
                raise ValueError(f"Unable to parse workbook {path.name}: {type(exc).__name__}") from exc
            return synthetic_dataset()
    if not any(frames[role] for role in ("sales", "sales_detail", "stock", "transit", "moq")):
        if not fallback_on_error:
            raise ValueError(f"No usable data sheets found in {root}")
        logger.warning("No usable data sheets found in %s; using synthetic sample data.", root)
        return synthetic_dataset()
    if frames["seasonality"]:
        logger.info("Found seasonality workbook(s); the engine derives seasonal factors from monthly sales history, so precomputed seasonal reports are not added as sales.")
    sales_frames = frames["sales"]
    if not sales_frames and frames["sales_detail"]:
        sales_frames = frames["sales_detail"]
    elif sales_frames and frames["sales_detail"]:
        logger.warning("Monthly sales workbooks are present; dynamic sales workbooks are not additionally summed to avoid duplicate sales.")

    dataset = Dataset()
    product_map: dict[str, Product] = {}
    sales_map: dict[tuple[str, str, date], float] = defaultdict(float)
    stock_map: dict[tuple[str, str], tuple[date, float]] = {}
    transit_map: dict[tuple[str, str], float] = defaultdict(float)
    moq_map: dict[str, Supplier] = {}
    stockout_months: dict[tuple[str, str], list[date]] = defaultdict(list)

    def product_info(frame: pd.DataFrame, row: pd.Series, sku: str) -> None:
        name_col, category_col = _column(frame, _NAME), _column(frame, _CATEGORY)
        if sku not in product_map:
            product_map[sku] = Product(sku, sku)
        current = product_map[sku]
        name = _text(row[name_col], current.name) if name_col is not None else current.name
        category = _text(row[category_col], current.category) if category_col is not None else current.category
        product_map[sku] = Product(sku, name or sku, category or "uncategorized")

    # Process sales and stock tables, including wide month-column exports.
    for role, role_frames in (("sales", sales_frames), ("stock", frames["stock"])):
        for frame in role_frames:
            sku_col = _column(frame, _SKU)
            qty_col = _column(frame, _QTY)
            date_col = _column(frame, _DATE)
            wh_col = _column(frame, _WAREHOUSE)
            month_cols = [(col, _month(col)) for col in frame.columns]
            month_cols = [(col, month) for col, month in month_cols if month is not None]
            if sku_col is None:
                logger.warning("Skipping %s sheet without an identifiable SKU column.", role)
                continue
            for _row_idx, row in frame.iterrows():
                sku = _text(row[sku_col])
                if not sku or sku.lower() == "nan":
                    continue
                warehouse = _text(row[wh_col], "DEFAULT") if wh_col is not None else "DEFAULT"
                product_info(frame, row, sku)
                if role == "sales":
                    if date_col is not None and qty_col is not None:
                        month = _month(row[date_col])
                        qty = _number(row[qty_col])
                        if month is not None and qty is not None:
                            sales_map[(sku, warehouse, month)] += qty
                    else:
                        for col, month in month_cols:
                            qty = _number(row[col])
                            if qty is not None:
                                sales_map[(sku, warehouse, month)] += qty
                else:
                    if date_col is not None and qty_col is not None:
                        month = _month(row[date_col])
                        qty = _number(row[qty_col])
                        if qty is not None:
                            snapshot = month or date.today()
                            key = (sku, warehouse)
                            if key not in stock_map or snapshot >= stock_map[key][0]:
                                stock_map[key] = (snapshot, qty)
                            if qty <= 0 and month:
                                stockout_months[key].append(month)
                    else:
                        for col, month in month_cols:
                            qty = _number(row[col])
                            if qty is None:
                                continue
                            key = (sku, warehouse)
                            if key not in stock_map or month >= stock_map[key][0]:
                                stock_map[key] = (month, qty)
                            if qty <= 0:
                                stockout_months[key].append(month)

    for (sku, warehouse, month), quantity in sales_map.items():
        dataset.sales.append(SalesMonth(month, sku, warehouse, quantity, None))
    dataset.stock = [Stock(sku, wh, snapshot[1]) for (sku, wh), snapshot in stock_map.items()]
    for (sku, wh), months in stockout_months.items():
        months = sorted(set(months))
        if months:
            run_start = previous = months[0]
            for month in months[1:]:
                prev_index = previous.year * 12 + previous.month
                month_index = month.year * 12 + month.month
                if month_index != prev_index + 1:
                    dataset.stockouts.append(Stockout(sku, wh, run_start, previous))
                    run_start = month
                previous = month
            dataset.stockouts.append(Stockout(sku, wh, run_start, previous))

    for frame in frames["transit"]:
        sku_col, qty_col = _column(frame, _SKU), _column(frame, _QTY)
        wh_col = _column(frame, _WAREHOUSE)
        if sku_col is None or qty_col is None:
            logger.warning("Skipping transit sheet missing SKU or quantity column.")
            continue
        for _, row in frame.iterrows():
            sku, qty = _text(row[sku_col]), _number(row[qty_col])
            if sku and qty is not None:
                wh = _text(row[wh_col], "DEFAULT") if wh_col is not None else "DEFAULT"
                transit_map[(sku, wh)] += qty
    dataset.transit = [Transit(sku, wh, qty) for (sku, wh), qty in transit_map.items()]

    for frame in frames["moq"]:
        sku_col, moq_col = _column(frame, _SKU), _column(frame, _MOQ)
        supplier_col, supplier_code_col = _column(frame, _SUPPLIER), _column(frame, _SUPPLIER_CODE)
        lead_col = _column(frame, _LEAD)
        if sku_col is None:
            logger.warning("Skipping MOQ sheet without an identifiable SKU column.")
            continue
        for _, row in frame.iterrows():
            sku = _text(row[sku_col])
            if not sku:
                continue
            moq = _number(row[moq_col]) if moq_col is not None else 0
            lead = _number(row[lead_col]) if lead_col is not None else None
            supplier_name = _text(row[supplier_col], "Unknown supplier") if supplier_col is not None else "Unknown supplier"
            supplier_code = _text(row[supplier_code_col], supplier_name) if supplier_code_col is not None else supplier_name
            moq_map[sku] = Supplier(sku, supplier_code, supplier_name,
                                    int(lead) if lead is not None and lead > 0 else 30,
                                    max(0, moq or 0))
            if lead is None:
                logger.warning("No lead time for SKU %s; using explicit 30-day default.", sku)
    dataset.suppliers = list(moq_map.values())
    dataset.products = list(product_map.values())
    logger.info("Loaded partner XLSX data: %d sales, %d stocks, %d transit, %d supplier terms, %d stockouts.",
                len(dataset.sales), len(dataset.stock), len(dataset.transit), len(dataset.suppliers), len(dataset.stockouts))
    return dataset


def load_dataset(raw_dir: str | Path, fallback_on_error: bool = True) -> Dataset:
    """Load partner data or fall back to deterministic synthetic records.

    Any unexpected structural/value error is surfaced as a warning and handled
    with the sample dataset so a bad workbook cannot prevent API startup.
    """
    try:
        return _load_dataset(raw_dir, fallback_on_error)
    except Exception as exc:
        if not fallback_on_error:
            raise
        logger.warning("Dataset load failed (%s: %s); using synthetic sample data.",
                       type(exc).__name__, exc)
        return synthetic_dataset()
