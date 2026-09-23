"""SQLite persistence for recommendation runs and explicit manager decisions."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


class OrderDatabase:
    """Small SQLite repository; each public operation uses its own connection."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS recommendation_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS recommendations (
                    item_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES recommendation_runs(run_id) ON DELETE CASCADE,
                    sku TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    warehouse TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    supplier_code TEXT NOT NULL,
                    supplier_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity >= 0),
                    forecast_monthly_demand REAL NOT NULL,
                    urgency TEXT NOT NULL,
                    justification_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'approved', 'rejected')),
                    approval_timestamp TEXT,
                    approved_by TEXT,
                    approved_at TEXT,
                    manager_note TEXT
                )
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(recommendations)")}
            if "approved_by" not in columns:
                connection.execute("ALTER TABLE recommendations ADD COLUMN approved_by TEXT")
            if "approved_at" not in columns:
                connection.execute("ALTER TABLE recommendations ADD COLUMN approved_at TEXT")
            connection.execute("""
                UPDATE recommendations
                SET approved_at = approval_timestamp,
                    approved_by = COALESCE(approved_by, 'manager')
                WHERE status = 'approved' AND (approved_at IS NULL OR approved_by IS NULL)
            """)
            connection.execute("CREATE INDEX IF NOT EXISTS idx_recommendations_run ON recommendations(run_id)")

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["id"] = result.pop("item_id")
        result["justification"] = json.loads(result.pop("justification_json"))
        return result

    def save_calculation(self, orders: list[dict[str, Any]]) -> dict[str, Any]:
        """Persist every recommendation as pending and return rows with stable IDs."""
        run_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        output = []
        with self._connection() as connection:
            connection.execute("INSERT INTO recommendation_runs(run_id, created_at) VALUES (?, ?)",
                               (run_id, created_at))
            for order in orders:
                item_id = str(uuid4())
                justification = order.get("justification", [])
                connection.execute("""
                    INSERT INTO recommendations (
                        item_id, run_id, sku, product_name, category, warehouse, unit,
                        supplier_code, supplier_name, quantity, forecast_monthly_demand,
                        urgency, justification_json, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """, (item_id, run_id, order["sku"], order["product_name"], order["category"],
                      order["warehouse"], order["unit"], order["supplier_code"],
                      order["supplier_name"], int(order["quantity"]),
                      float(order["forecast_monthly_demand"]), order["urgency"],
                      json.dumps(justification, ensure_ascii=False)))
                output.append({**order, "id": item_id, "status": "pending",
                               "approval_timestamp": None, "approved_by": None,
                               "approved_at": None, "manager_note": None})
        return {"api_version": "v1", "run_id": run_id, "created_at": created_at, "orders": output}

    def latest_orders(self) -> dict[str, Any]:
        with self._connection() as connection:
            run = connection.execute("""
                SELECT run_id, created_at FROM recommendation_runs
                ORDER BY created_at DESC, rowid DESC LIMIT 1
            """).fetchone()
            if run is None:
                return {"api_version": "v1", "run_id": None, "orders": []}
            rows = connection.execute("""
                SELECT * FROM recommendations WHERE run_id = ? ORDER BY supplier_code, sku, item_id
            """, (run["run_id"],)).fetchall()
            return {"api_version": "v1", "run_id": run["run_id"], "created_at": run["created_at"],
                    "orders": [self._row(row) for row in rows]}

    def approve(self, item_ids: list[str], supplier_codes: list[str],
                manager_note: str | None = None,
                approved_by: str = "manager") -> dict[str, Any]:
        """Approve matching pending items in the latest run only."""
        filters: list[str] = []
        if item_ids:
            placeholders = ",".join("?" for _ in item_ids)
            filters.append(f"item_id IN ({placeholders})")
        if supplier_codes:
            placeholders = ",".join("?" for _ in supplier_codes)
            filters.append(f"supplier_code IN ({placeholders})")
        if not filters:
            return {"run_id": None, "approved": [], "already_approved": [], "approval_timestamp": None}
        where = " OR ".join(f"({part})" for part in filters)
        targets = [*item_ids, *supplier_codes]
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute("""
                SELECT run_id FROM recommendation_runs
                ORDER BY created_at DESC, rowid DESC LIMIT 1
            """).fetchone()
            if latest is None:
                return {"run_id": None, "approved": [], "already_approved": [], "approval_timestamp": None}
            run_id = latest["run_id"]
            matching_rows = connection.execute(f"""
                SELECT item_id, status, approval_timestamp, approved_at, approved_by FROM recommendations
                WHERE run_id = ? AND status IN ('pending', 'approved') AND ({where})
                ORDER BY item_id
            """, [run_id, *targets]).fetchall()
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(f"""
                UPDATE recommendations SET status = 'approved', approval_timestamp = ?,
                    approved_at = ?, approved_by = ?, manager_note = ?
                WHERE run_id = ? AND status = 'pending' AND ({where})
            """, [now, now, approved_by, manager_note, run_id, *targets])
        approved_ids = [row["item_id"] for row in matching_rows if row["status"] == "pending"]
        already_approved_ids = [row["item_id"] for row in matching_rows if row["status"] == "approved"]
        approval_timestamps = {
            row["item_id"]: (now if row["status"] == "pending" else
                             row["approved_at"] or row["approval_timestamp"])
            for row in matching_rows
            if row["status"] == "pending" or row["approved_at"] or row["approval_timestamp"]
        }
        approval_actors = {
            row["item_id"]: (approved_by if row["status"] == "pending" else row["approved_by"])
            for row in matching_rows
        }
        response_timestamp = (now if approved_ids else
                              approval_timestamps.get(already_approved_ids[0])
                              if len(already_approved_ids) == 1 else None)
        response_actor = (approved_by if approved_ids else
                          approval_actors.get(already_approved_ids[0])
                          if len(already_approved_ids) == 1 else None)
        return {"run_id": run_id, "approved": approved_ids, "already_approved": already_approved_ids,
                "approval_timestamp": response_timestamp,
                "approval_timestamps": approval_timestamps,
                "approved_by": response_actor, "approval_actors": approval_actors}

    def approved_latest(self, approval_date: str | None = None,
                        supplier_code: str | None = None,
                        warehouse: str | None = None) -> list[dict[str, Any]]:
        with self._connection() as connection:
            run = connection.execute("""
                SELECT run_id FROM recommendation_runs
                ORDER BY created_at DESC, rowid DESC LIMIT 1
            """).fetchone()
            if run is None:
                return []
            supplier_value = "CASE WHEN lower(trim(supplier_code)) IN ('', 'unknown', 'unknown supplier') THEN NULLIF(trim(supplier_name), '') ELSE trim(supplier_code) END"
            clauses = ["run_id = ?", "status = 'approved'", f"{supplier_value} IS NOT NULL",
                       f"lower({supplier_value}) NOT IN ('unknown', 'unknown supplier')"]
            parameters: list[Any] = [run["run_id"]]
            if approval_date:
                clauses.append("date(COALESCE(approved_at, approval_timestamp)) = ?")
                parameters.append(approval_date)
            if supplier_code:
                clauses.append(f"{supplier_value} = ?")
                parameters.append(supplier_code)
            if warehouse:
                clauses.append("warehouse = ?")
                parameters.append(warehouse)
            rows = connection.execute(f"""
                SELECT item_id, {supplier_value} AS supplier_code, sku, quantity, warehouse
                FROM recommendations
                WHERE {' AND '.join(clauses)}
                ORDER BY supplier_code, sku, warehouse
            """, parameters).fetchall()
            return [dict(row) for row in rows]
