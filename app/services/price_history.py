import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.core.config import settings
from app.models.comparison import ComparisonResponse
from app.models.product import StoreProduct

logger = logging.getLogger(__name__)


class TrackedItem(BaseModel):
    """A grocery item enrolled in weekly price tracking."""

    query: str
    query_cs: Optional[str] = None
    category: Optional[str] = None
    active: bool = True
    latest_rohlik_unit_price: Optional[float] = None
    latest_kosik_unit_price: Optional[float] = None
    latest_unit_type: Optional[str] = None
    last_checked_at: Optional[str] = None


class PriceSnapshotPoint(BaseModel):
    """Single historical price-per-unit data point for plotting."""

    store: str
    product_name: str
    brand: Optional[str] = None
    price: float
    unit_price: Optional[float] = None
    unit_type: Optional[str] = None
    is_on_sale: bool = False
    recorded_at: str


class ItemPriceHistory(BaseModel):
    """Time-series price history for a grocery item across both stores."""

    query: str
    unit_type: str = "kg"
    rohlik_series: List[PriceSnapshotPoint] = Field(default_factory=list)
    kosik_series: List[PriceSnapshotPoint] = Field(default_factory=list)


class PriceHistoryStats(BaseModel):
    """Summary metrics for the price tracking database."""

    tracked_items_count: int
    total_snapshots: int
    last_recorded_at: Optional[str] = None


class PriceHistoryService:
    """SQLite-backed storage for tracked grocery items and historical unit-price snapshots."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path if db_path is not None else settings.price_history_db_path
        self._memory_conn: Optional[sqlite3.Connection] = None

        if str(self.db_path) != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)

        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        return sqlite3.connect(str(self.db_path))

    def _init_schema(self) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tracked_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT UNIQUE NOT NULL,
                    query_cs TEXT,
                    category TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS price_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_query TEXT NOT NULL,
                    store TEXT NOT NULL,
                    product_id TEXT,
                    product_name TEXT NOT NULL,
                    brand TEXT,
                    price REAL NOT NULL,
                    unit_price REAL,
                    unit_type TEXT,
                    is_on_sale INTEGER NOT NULL DEFAULT 0,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_snapshots_item_time
                ON price_snapshots (item_query, recorded_at)
                """
            )
            conn.commit()
        finally:
            if self._memory_conn is None:
                conn.close()

    @staticmethod
    def _normalize_query(query: str) -> str:
        return " ".join(query.strip().lower().split())

    def seed_default_items(self, items: Dict[str, List[str]]) -> None:
        """Seed initial watchlist from bilingual dictionary if tracked_items is empty."""
        conn = self._get_connection()
        try:
            count_row = conn.execute("SELECT COUNT(*) FROM tracked_items").fetchone()
            if count_row and int(count_row[0]) > 0:
                return
            rows = [
                (self._normalize_query(en), cs_list[0] if cs_list else None, None)
                for en, cs_list in items.items()
                if en.strip()
            ]
            conn.executemany(
                "INSERT OR IGNORE INTO tracked_items (query, query_cs, category) VALUES (?, ?, ?)",
                rows,
            )
            conn.commit()
        finally:
            if self._memory_conn is None:
                conn.close()

    def add_tracked_item(
        self, query: str, query_cs: Optional[str] = None, category: Optional[str] = None
    ) -> TrackedItem:
        """Add or re-activate a grocery item in the weekly watchlist."""
        norm = self._normalize_query(query)
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO tracked_items (query, query_cs, category, active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(query) DO UPDATE SET
                    active = 1,
                    query_cs = COALESCE(excluded.query_cs, tracked_items.query_cs),
                    category = COALESCE(excluded.category, tracked_items.category)
                """,
                (norm, query_cs, category),
            )
            conn.commit()
            return TrackedItem(query=norm, query_cs=query_cs, category=category, active=True)
        finally:
            if self._memory_conn is None:
                conn.close()

    def remove_tracked_item(self, query: str) -> bool:
        """Deactivate a grocery item from the weekly watchlist."""
        norm = self._normalize_query(query)
        conn = self._get_connection()
        try:
            cur = conn.execute("UPDATE tracked_items SET active = 0 WHERE query = ?", (norm,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            if self._memory_conn is None:
                conn.close()

    def list_tracked_items(self, active_only: bool = True) -> List[TrackedItem]:
        """Return tracked items enriched with their most recent recorded unit price per store."""
        conn = self._get_connection()
        try:
            where = "WHERE t.active = 1" if active_only else ""
            rows = conn.execute(
                f"""
                SELECT
                    t.query,
                    t.query_cs,
                    t.category,
                    t.active,
                    (SELECT s.unit_price FROM price_snapshots s
                     WHERE s.item_query = t.query AND s.store = 'rohlik'
                     ORDER BY s.recorded_at DESC, s.id DESC LIMIT 1) AS r_unit_price,
                    (SELECT s.unit_price FROM price_snapshots s
                     WHERE s.item_query = t.query AND s.store = 'kosik'
                     ORDER BY s.recorded_at DESC, s.id DESC LIMIT 1) AS k_unit_price,
                    (SELECT s.unit_type FROM price_snapshots s
                     WHERE s.item_query = t.query AND s.unit_type IS NOT NULL
                     ORDER BY s.recorded_at DESC, s.id DESC LIMIT 1) AS unit_type,
                    (SELECT MAX(s.recorded_at) FROM price_snapshots s
                     WHERE s.item_query = t.query) AS last_checked_at
                FROM tracked_items t
                {where}
                ORDER BY t.query ASC
                """
            ).fetchall()

            return [
                TrackedItem(
                    query=r[0],
                    query_cs=r[1],
                    category=r[2],
                    active=bool(r[3]),
                    latest_rohlik_unit_price=float(r[4]) if r[4] is not None else None,
                    latest_kosik_unit_price=float(r[5]) if r[5] is not None else None,
                    latest_unit_type=r[6],
                    last_checked_at=r[7],
                )
                for r in rows
            ]
        finally:
            if self._memory_conn is None:
                conn.close()

    def record_comparison(
        self, comparison: ComparisonResponse, recorded_at: Optional[datetime] = None
    ) -> int:
        """Persist best-value normalized unit prices for both stores from a comparison response."""
        norm = self._normalize_query(comparison.query)
        ts_str = (recorded_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")

        r_best: Optional[StoreProduct] = (
            comparison.rohlik_ranked[0]
            if comparison.rohlik_ranked
            else (comparison.primary_pair.rohlik_product if comparison.primary_pair else None)
        )
        k_best: Optional[StoreProduct] = (
            comparison.kosik_ranked[0]
            if comparison.kosik_ranked
            else (comparison.primary_pair.kosik_product if comparison.primary_pair else None)
        )

        rows_to_insert = []
        for store_name, prod in (("rohlik", r_best), ("kosik", k_best)):
            if prod is None:
                continue
            rows_to_insert.append(
                (
                    norm,
                    store_name,
                    prod.product_id,
                    prod.name,
                    prod.brand,
                    float(prod.price),
                    float(prod.unit_price) if prod.unit_price is not None else None,
                    prod.unit_type.value if prod.unit_type else None,
                    1 if prod.is_on_sale else 0,
                    ts_str,
                )
            )

        if not rows_to_insert:
            return 0

        conn = self._get_connection()
        try:
            # Update metadata on tracked item if it exists
            conn.execute(
                """
                UPDATE tracked_items
                SET query_cs = COALESCE(?, query_cs),
                    category = COALESCE(?, category)
                WHERE query = ?
                """,
                (comparison.query_translated, comparison.category, norm),
            )
            conn.executemany(
                """
                INSERT INTO price_snapshots (
                    item_query, store, product_id, product_name, brand,
                    price, unit_price, unit_type, is_on_sale, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows_to_insert,
            )
            conn.commit()
            return len(rows_to_insert)
        finally:
            if self._memory_conn is None:
                conn.close()

    def get_item_history(self, query: str, days: int = 90) -> ItemPriceHistory:
        """Retrieve time-series unit-price snapshots for plotting Rohlík vs Košík over time."""
        norm = self._normalize_query(query)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT store, product_name, brand, price, unit_price, unit_type, is_on_sale, recorded_at
                FROM price_snapshots
                WHERE item_query = ? AND recorded_at >= ?
                ORDER BY recorded_at ASC, id ASC
                """,
                (norm, cutoff),
            ).fetchall()

            rohlik_series: List[PriceSnapshotPoint] = []
            kosik_series: List[PriceSnapshotPoint] = []
            detected_unit = "kg"

            for r in rows:
                point = PriceSnapshotPoint(
                    store=r[0],
                    product_name=r[1],
                    brand=r[2],
                    price=float(r[3]),
                    unit_price=float(r[4]) if r[4] is not None else None,
                    unit_type=r[5],
                    is_on_sale=bool(r[6]),
                    recorded_at=r[7],
                )
                if r[5]:
                    detected_unit = r[5]
                if r[0] == "rohlik":
                    rohlik_series.append(point)
                elif r[0] == "kosik":
                    kosik_series.append(point)

            return ItemPriceHistory(
                query=norm,
                unit_type=detected_unit,
                rohlik_series=rohlik_series,
                kosik_series=kosik_series,
            )
        finally:
            if self._memory_conn is None:
                conn.close()

    def get_stats(self) -> PriceHistoryStats:
        """Return aggregate counts and latest snapshot timestamp."""
        conn = self._get_connection()
        try:
            item_row = conn.execute("SELECT COUNT(*) FROM tracked_items WHERE active = 1").fetchone()
            snap_row = conn.execute("SELECT COUNT(*), MAX(recorded_at) FROM price_snapshots").fetchone()
            return PriceHistoryStats(
                tracked_items_count=int(item_row[0]) if item_row else 0,
                total_snapshots=int(snap_row[0]) if snap_row else 0,
                last_recorded_at=snap_row[1] if snap_row else None,
            )
        finally:
            if self._memory_conn is None:
                conn.close()

    def close(self) -> None:
        """Close persistent in-memory connection if open."""
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None
