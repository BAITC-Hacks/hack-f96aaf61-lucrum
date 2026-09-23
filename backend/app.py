"""FastAPI wrapper with XLSX loading at application startup."""
import csv
import io
import logging
import os
import re
import sqlite3
import uuid
import zipfile
from io import BytesIO
from contextlib import asynccontextmanager
from datetime import date as Date
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .engine import Dataset, calculate, grouped_orders, stock_status
from .db import OrderDatabase
from .loader import load_dataset

logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_dataset = Dataset()
_last_calculation = {"api_version": "v1", "orders": []}
_database: OrderDatabase | None = None


class OrderApproveRequest(BaseModel):
    """Explicit manager decision for one or more currently recommended items."""

    item_ids: list[str] = Field(default_factory=list, examples=[["d12a696c-264c-4d63-a59e-639e644208b8"]],
                                description="Recommendation item IDs to approve.")
    supplier_codes: list[str] = Field(default_factory=list, examples=[["SUP-001"]],
                                      description="Approve every pending line for these suppliers in the latest run.")
    confirmed: bool = Field(default=False, examples=[True],
                            description="Must be true to record the manager's explicit confirmation.")
    manager_note: str | None = Field(default=None, max_length=1000,
                                     examples=["Проверено, товар в наличии"],
                                     description="Optional note saved with the approval decision.")
    approved_by: str = Field(default="manager", min_length=1, max_length=200,
                             examples=["John Doe"], description="Manager name or identifier for the audit trail.")


class OrderApproveResponse(BaseModel):
    api_version: Literal["v1"] = Field(..., examples=["v1"])
    run_id: str = Field(..., examples=["36f2b240-30c7-463d-a3cf-8a3ba22d2270"])
    approved: list[str] = Field(..., examples=[["d12a696c-264c-4d63-a59e-639e644208b8"]])
    already_approved: list[str] = Field(..., examples=[[]])
    approval_timestamp: str | None = Field(..., examples=["2025-03-08T12:30:00+00:00"])
    approval_timestamps: dict[str, str] = Field(..., examples=[{
        "d12a696c-264c-4d63-a59e-639e644208b8": "2025-03-08T12:30:00+00:00"
    }])
    approved_by: str | None = Field(..., examples=["John Doe"])
    approval_actors: dict[str, str | None] = Field(..., examples=[{
        "d12a696c-264c-4d63-a59e-639e644208b8": "John Doe"
    }])
    status: Literal["approved"] = Field(..., examples=["approved"])
    message: str = Field(..., examples=["Items approved"])


def _db() -> OrderDatabase:
    if _database is None:
        raise HTTPException(status_code=503, detail="Order database is not initialized")
    return _database


def _raw_dir() -> Path:
    return Path(os.environ.get("LUCRUM_RAW_DIR", Path(__file__).resolve().parents[1] / "data" / "raw"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize persistence and load partner files, falling back to sample data."""
    global _database
    db_path = os.environ.get("LUCRUM_DB_PATH", str(Path(__file__).resolve().parents[1] / "data" / "lucrum.sqlite3"))
    _database = OrderDatabase(db_path)
    raw_dir = _raw_dir()
    set_dataset(load_dataset(raw_dir))
    logger.info("Lucrum API initialized from %s.", raw_dir)
    yield


app = FastAPI(title="Lucrum Procurement API", version="1.0.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "api_version": "v1"}


@app.post("/api/calculate")
def calculate_orders(warehouse: str | None = None, category: str | None = None) -> dict[str, Any]:
    global _last_calculation
    result = calculate(_dataset, warehouse, category)
    _last_calculation = _db().save_calculation(result["orders"])
    return _last_calculation


@app.get("/api/orders")
def get_orders() -> dict[str, Any]:
    latest = _db().latest_orders()
    return {**grouped_orders(latest), "run_id": latest["run_id"]}


@app.post("/api/orders/approve", response_model=OrderApproveResponse)
def approve_orders(request: OrderApproveRequest) -> OrderApproveResponse:
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Explicit manager confirmation is required")
    if not request.item_ids and not request.supplier_codes:
        raise HTTPException(status_code=422, detail="Provide item_ids and/or supplier_codes")
    logger.info("Approval request received: item IDs=%s supplier codes=%s approved_by=%s",
                request.item_ids, request.supplier_codes, request.approved_by)
    try:
        result = _db().approve(request.item_ids, request.supplier_codes,
                               request.manager_note, request.approved_by)
    except sqlite3.Error as exc:
        logger.exception("Database error while approving order items")
        raise HTTPException(status_code=503, detail="Order approval could not be saved") from exc
    if not result["approved"] and not result["already_approved"]:
        raise HTTPException(status_code=409, detail="No pending matching order items in the latest calculation")
    if result["already_approved"] and not result["approved"]:
        message = "Item is already approved" if len(result["already_approved"]) == 1 else "All matching items are already approved"
    elif result["already_approved"]:
        message = "Pending items approved; some matching items were already approved"
    else:
        message = "Items approved"
    logger.info("Approval processed for run %s: approved=%d already approved=%d IDs=%s",
                result["run_id"], len(result["approved"]), len(result["already_approved"]),
                result["approved"] + result["already_approved"])
    return OrderApproveResponse(api_version="v1", **result, status="approved", message=message)


@app.get("/api/orders/export-1c", responses={404: {"description": "No approved positions found for export"}})
def export_1c(approval_date: Date | None = Query(default=None, alias="date"),
              supplier_code: str | None = None,
              warehouse: str | None = None) -> StreamingResponse:
    logger.info("1C export requested: date=%s supplier_code=%s warehouse=%s",
                approval_date, supplier_code, warehouse)
    try:
        rows = _db().approved_latest(approval_date.isoformat() if approval_date else None,
                                     supplier_code, warehouse)
    except sqlite3.Error as exc:
        logger.exception("Database error while querying approved items for 1C export")
        raise HTTPException(status_code=503, detail="Approved orders could not be read for export") from exc
    logger.info("1C export found %d approved order item(s); item IDs=%s",
                len(rows), [row["item_id"] for row in rows])
    if not rows:
        raise HTTPException(status_code=404, detail="No approved positions found for export")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["SupplierCode", "SKU", "Quantity", "Warehouse"])
    writer.writeheader()
    writer.writerows({"SupplierCode": row["supplier_code"], "SKU": row["sku"],
                      "Quantity": row["quantity"], "Warehouse": row["warehouse"]}
                     for row in rows)
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=approved_orders_1c.csv"})


@app.post("/api/upload")
async def upload_report(file: UploadFile = File(...)) -> dict[str, Any]:
    """Store an XLSX report and atomically activate the successfully loaded dataset."""
    original = (file.filename or "").replace("\\", "/")
    basename = Path(original).name
    if not basename or basename in {".", ".."} or Path(basename).suffix.lower() != ".xlsx":
        raise HTTPException(status_code=400, detail="Upload must be an .xlsx workbook")

    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Upload exceeds {MAX_UPLOAD_BYTES} byte limit")
    try:
        with zipfile.ZipFile(BytesIO(contents)) as archive:
            members = archive.infolist()
            names = {member.filename for member in members}
            unpacked_size = sum(member.file_size for member in members)
            valid_xlsx = {"[Content_Types].xml", "xl/workbook.xml"}.issubset(names)
            if len(members) > 5000 or unpacked_size > 100 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Workbook expands beyond the allowed limit")
            if not valid_xlsx:
                raise HTTPException(status_code=400, detail="ZIP file is not an XLSX workbook")
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="File is not a valid XLSX ZIP container")
    except OSError as exc:
        raise HTTPException(status_code=400, detail="File is not a readable XLSX ZIP container") from exc

    raw_dir = _raw_dir()
    raw_dir.mkdir(parents=True, exist_ok=True)
    stem = (re.sub(r"[^\w.-]+", "_", Path(basename).stem, flags=re.UNICODE).strip("._")
            or "partner_report")[:100]
    destination = raw_dir / f"{stem}-{uuid.uuid4().hex[:10]}.xlsx"
    temporary = raw_dir / f".upload-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(contents)
        os.replace(temporary, destination)
        try:
            updated_dataset = load_dataset(raw_dir, fallback_on_error=False)
            calculate(updated_dataset)  # validate the loaded records before activation
        except Exception as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=f"Workbook could not be loaded: {type(exc).__name__}") from exc
        set_dataset(updated_dataset)
        _db().save_calculation([])  # invalidate prior approvals after the source dataset changes
    finally:
        temporary.unlink(missing_ok=True)
        await file.close()
    return {"api_version": "v1", "filename": destination.name, "reloaded": True,
            "counts": {"sales": len(updated_dataset.sales), "stock": len(updated_dataset.stock),
                       "transit": len(updated_dataset.transit), "suppliers": len(updated_dataset.suppliers),
                       "products": len(updated_dataset.products), "stockouts": len(updated_dataset.stockouts)}}


@app.get("/api/stock")
def get_stock(warehouse: str | None = None) -> dict:
    return stock_status(_dataset, warehouse)


def set_dataset(data: Dataset) -> None:
    """Injection point for an approved, privacy-screened data adapter."""
    global _dataset, _last_calculation
    _dataset = data
    _last_calculation = calculate(data)
