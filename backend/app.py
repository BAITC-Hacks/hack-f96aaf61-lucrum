"""FastAPI wrapper with XLSX loading at application startup."""
import csv
import io
import logging
import os
import re
import uuid
import zipfile
from io import BytesIO
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
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


class ApprovalRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list)
    supplier_codes: list[str] = Field(default_factory=list)
    confirmed: bool = False
    manager_note: str | None = Field(default=None, max_length=1000)


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


@app.post("/api/orders/approve")
def approve_orders(request: ApprovalRequest) -> dict[str, Any]:
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Explicit manager confirmation is required")
    if not request.item_ids and not request.supplier_codes:
        raise HTTPException(status_code=422, detail="Provide item_ids and/or supplier_codes")
    result = _db().approve(request.item_ids, request.supplier_codes, request.manager_note)
    if not result["approved"]:
        raise HTTPException(status_code=409, detail="No pending matching order items in the latest calculation")
    logger.info("Approved %d order item(s) in run %s; item IDs=%s",
                len(result["approved"]), result["run_id"], result["approved"])
    return {"api_version": "v1", **result, "status": "approved"}


@app.get("/api/orders/export-1c")
def export_1c() -> StreamingResponse:
    rows = _db().approved_latest()
    logger.info("1C export found %d approved order item(s); item IDs=%s",
                len(rows), [row["item_id"] for row in rows])
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
