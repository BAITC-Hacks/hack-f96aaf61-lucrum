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
                    manager_note TEXT
                )
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
                               "approval_timestamp": None, "manager_note": None})
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
                manager_note: str | None = None) -> dict[str, Any]:
        """Approve matching pending items in the latest run only."""
        latest = self.latest_orders()
        run_id = latest["run_id"]
        if run_id is None:
            return {"run_id": None, "approved": [], "approval_timestamp": None}
        now = datetime.now(timezone.utc).isoformat()
        filters: list[str] = []
        parameters: list[Any] = [now, manager_note, run_id]
        if item_ids:
            placeholders = ",".join("?" for _ in item_ids)
            filters.append(f"item_id IN ({placeholders})")
            parameters.extend(item_ids)
        if supplier_codes:
            placeholders = ",".join("?" for _ in supplier_codes)
            filters.append(f"supplier_code IN ({placeholders})")
            parameters.extend(supplier_codes)
        if not filters:
            return {"run_id": run_id, "approved": [], "approval_timestamp": None}
        where = " OR ".join(f"({part})" for part in filters)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            approved_rows = connection.execute(f"""
                SELECT item_id FROM recommendations
                WHERE run_id = ? AND status = 'pending' AND ({where})
                ORDER BY item_id
            """, [run_id, *parameters[3:]]).fetchall()
            cursor = connection.execute(f"""
                UPDATE recommendations SET status = 'approved', approval_timestamp = ?, manager_note = ?
                WHERE run_id = ? AND status = 'pending' AND ({where})
            """, parameters)
        return {"run_id": run_id, "approved": [row["item_id"] for row in approved_rows],
                "approval_timestamp": now if cursor.rowcount else None}

    def approved_latest(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            run = connection.execute("""
                SELECT run_id FROM recommendation_runs
                ORDER BY created_at DESC, rowid DESC LIMIT 1
            """).fetchone()
            if run is None:
                return []
            rows = connection.execute("""
                SELECT item_id, supplier_code, sku, quantity, warehouse FROM recommendations
                WHERE run_id = ? AND status = 'approved'
                ORDER BY supplier_code, sku, warehouse
            """, (run["run_id"],)).fetchall()
            return [dict(row) for row in rows]
