import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, create_engine, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.models.comparison import ComparisonResponse
from app.models.product import StoreProduct

logger = logging.getLogger(__name__)


class PriceHistoryBase(DeclarativeBase):
    """SQLAlchemy declarative base for price tracking models."""


class TrackedItemRecord(PriceHistoryBase):
    """ORM model for a grocery item enrolled in weekly price tracking."""

    __tablename__ = "tracked_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    query_cs: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class PriceSnapshotRecord(PriceHistoryBase):
    """ORM model for a recorded store product price-per-unit snapshot."""

    __tablename__ = "price_snapshots"
    __table_args__ = (
        Index("idx_snapshots_item_time", "item_query", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_query: Mapped[str] = mapped_column(String, nullable=False)
    store: Mapped[str] = mapped_column(String, nullable=False)
    product_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    product_name: Mapped[str] = mapped_column(String, nullable=False)
    brand: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_on_sale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


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
    """SQLAlchemy-backed storage for tracked grocery items and historical unit-price snapshots."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path if db_path is not None else settings.price_history_db_path

        if str(self.db_path) == ":memory:":
            self.engine = create_engine(
                "sqlite:///:memory:",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(
                f"sqlite:///{Path(self.db_path).resolve()}",
                connect_args={"check_same_thread": False},
            )

        PriceHistoryBase.metadata.create_all(self.engine)

    @staticmethod
    def _normalize_query(query: str) -> str:
        return " ".join(query.strip().lower().split())

    def seed_from_yaml(self, yaml_path: Path) -> int:
        """Idempotently seed tracked groceries from config/tracked_groceries.yaml."""
        if not yaml_path.exists():
            return 0

        import yaml

        with open(yaml_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        entries = raw.get("groceries", [])
        if not entries:
            return 0

        now = datetime.now(timezone.utc)
        values = [
            {
                "query": self._normalize_query(entry["query"]),
                "query_cs": entry.get("query_cs"),
                "category": entry.get("category"),
                "active": True,
                "created_at": now,
            }
            for entry in entries
            if entry.get("query")
        ]
        if not values:
            return 0

        with Session(self.engine) as session:
            stmt = sqlite_insert(TrackedItemRecord).values(values).on_conflict_do_nothing(
                index_elements=["query"]
            )
            res = session.execute(stmt)
            session.commit()
            return res.rowcount or 0

    def seed_default_items(self, items: Dict[str, List[str]]) -> None:
        """Seed initial watchlist from bilingual dictionary if tracked_items is empty."""
        with Session(self.engine) as session:
            existing_count = session.scalar(select(func.count()).select_from(TrackedItemRecord))
            if existing_count and int(existing_count) > 0:
                return

            now = datetime.now(timezone.utc)
            values = [
                {
                    "query": self._normalize_query(en),
                    "query_cs": cs_list[0] if cs_list else None,
                    "category": None,
                    "active": True,
                    "created_at": now,
                }
                for en, cs_list in items.items()
                if en.strip()
            ]
            if values:
                stmt = sqlite_insert(TrackedItemRecord).values(values).on_conflict_do_nothing(
                    index_elements=["query"]
                )
                session.execute(stmt)
                session.commit()

    def add_tracked_item(
        self, query: str, query_cs: Optional[str] = None, category: Optional[str] = None
    ) -> TrackedItem:
        """Add or re-activate a grocery item in the weekly watchlist."""
        norm = self._normalize_query(query)
        with Session(self.engine) as session:
            stmt = sqlite_insert(TrackedItemRecord).values(
                query=norm,
                query_cs=query_cs,
                category=category,
                active=True,
                created_at=datetime.now(timezone.utc),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["query"],
                set_={
                    "active": True,
                    "query_cs": func.coalesce(stmt.excluded.query_cs, TrackedItemRecord.query_cs),
                    "category": func.coalesce(stmt.excluded.category, TrackedItemRecord.category),
                },
            )
            session.execute(stmt)
            session.commit()
            return TrackedItem(query=norm, query_cs=query_cs, category=category, active=True)

    def remove_tracked_item(self, query: str) -> bool:
        """Deactivate a grocery item from the weekly watchlist."""
        norm = self._normalize_query(query)
        with Session(self.engine) as session:
            result = session.execute(
                update(TrackedItemRecord)
                .where(TrackedItemRecord.query == norm)
                .values(active=False)
            )
            session.commit()
            return (result.rowcount or 0) > 0

    def list_tracked_items(self, active_only: bool = True) -> List[TrackedItem]:
        """Return tracked items enriched with their most recent recorded unit price per store."""
        with Session(self.engine) as session:
            r_unit_subq = (
                select(PriceSnapshotRecord.unit_price)
                .where(
                    PriceSnapshotRecord.item_query == TrackedItemRecord.query,
                    PriceSnapshotRecord.store == "rohlik",
                )
                .order_by(PriceSnapshotRecord.recorded_at.desc(), PriceSnapshotRecord.id.desc())
                .limit(1)
                .scalar_subquery()
            )
            k_unit_subq = (
                select(PriceSnapshotRecord.unit_price)
                .where(
                    PriceSnapshotRecord.item_query == TrackedItemRecord.query,
                    PriceSnapshotRecord.store == "kosik",
                )
                .order_by(PriceSnapshotRecord.recorded_at.desc(), PriceSnapshotRecord.id.desc())
                .limit(1)
                .scalar_subquery()
            )
            unit_type_subq = (
                select(PriceSnapshotRecord.unit_type)
                .where(
                    PriceSnapshotRecord.item_query == TrackedItemRecord.query,
                    PriceSnapshotRecord.unit_type.is_not(None),
                )
                .order_by(PriceSnapshotRecord.recorded_at.desc(), PriceSnapshotRecord.id.desc())
                .limit(1)
                .scalar_subquery()
            )
            last_checked_subq = (
                select(func.max(PriceSnapshotRecord.recorded_at))
                .where(PriceSnapshotRecord.item_query == TrackedItemRecord.query)
                .scalar_subquery()
            )

            stmt = select(
                TrackedItemRecord.query,
                TrackedItemRecord.query_cs,
                TrackedItemRecord.category,
                TrackedItemRecord.active,
                r_unit_subq,
                k_unit_subq,
                unit_type_subq,
                last_checked_subq,
            )
            if active_only:
                stmt = stmt.where(TrackedItemRecord.active.is_(True))
            stmt = stmt.order_by(TrackedItemRecord.query.asc())

            rows = session.execute(stmt).all()
            return [
                TrackedItem(
                    query=r[0],
                    query_cs=r[1],
                    category=r[2],
                    active=bool(r[3]),
                    latest_rohlik_unit_price=float(r[4]) if r[4] is not None else None,
                    latest_kosik_unit_price=float(r[5]) if r[5] is not None else None,
                    latest_unit_type=r[6],
                    last_checked_at=r[7].strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(r[7], datetime)
                    else (str(r[7]) if r[7] is not None else None),
                )
                for r in rows
            ]

    def record_comparison(
        self, comparison: ComparisonResponse, recorded_at: Optional[datetime] = None
    ) -> int:
        """Persist best-value normalized unit prices for both stores from a comparison response."""
        norm = self._normalize_query(comparison.query)
        ts = recorded_at or datetime.now(timezone.utc)

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

        snapshots: List[PriceSnapshotRecord] = []
        for store_name, prod in (("rohlik", r_best), ("kosik", k_best)):
            if prod is None:
                continue
            snapshots.append(
                PriceSnapshotRecord(
                    item_query=norm,
                    store=store_name,
                    product_id=prod.product_id,
                    product_name=prod.name,
                    brand=prod.brand,
                    price=float(prod.price),
                    unit_price=float(prod.unit_price) if prod.unit_price is not None else None,
                    unit_type=prod.unit_type.value if prod.unit_type else None,
                    is_on_sale=bool(prod.is_on_sale),
                    recorded_at=ts,
                )
            )

        if not snapshots:
            return 0

        with Session(self.engine) as session:
            session.execute(
                update(TrackedItemRecord)
                .where(TrackedItemRecord.query == norm)
                .values(
                    query_cs=func.coalesce(comparison.query_translated, TrackedItemRecord.query_cs),
                    category=func.coalesce(comparison.category, TrackedItemRecord.category),
                )
            )
            session.add_all(snapshots)
            session.commit()
            return len(snapshots)

    def get_item_history(self, query: str, days: int = 90) -> ItemPriceHistory:
        """Retrieve time-series unit-price snapshots for plotting Rohlík vs Košík over time."""
        norm = self._normalize_query(query)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        with Session(self.engine) as session:
            rows = session.scalars(
                select(PriceSnapshotRecord)
                .where(
                    PriceSnapshotRecord.item_query == norm,
                    PriceSnapshotRecord.recorded_at >= cutoff,
                )
                .order_by(PriceSnapshotRecord.recorded_at.asc(), PriceSnapshotRecord.id.asc())
            ).all()

            rohlik_series: List[PriceSnapshotPoint] = []
            kosik_series: List[PriceSnapshotPoint] = []
            detected_unit = "kg"

            for row in rows:
                ts_str = (
                    row.recorded_at.strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(row.recorded_at, datetime)
                    else str(row.recorded_at)
                )
                point = PriceSnapshotPoint(
                    store=row.store,
                    product_name=row.product_name,
                    brand=row.brand,
                    price=float(row.price),
                    unit_price=float(row.unit_price) if row.unit_price is not None else None,
                    unit_type=row.unit_type,
                    is_on_sale=bool(row.is_on_sale),
                    recorded_at=ts_str,
                )
                if row.unit_type:
                    detected_unit = row.unit_type
                if row.store == "rohlik":
                    rohlik_series.append(point)
                elif row.store == "kosik":
                    kosik_series.append(point)

            return ItemPriceHistory(
                query=norm,
                unit_type=detected_unit,
                rohlik_series=rohlik_series,
                kosik_series=kosik_series,
            )

    def get_stats(self) -> PriceHistoryStats:
        """Return aggregate counts and latest snapshot timestamp."""
        with Session(self.engine) as session:
            items_count = session.scalar(
                select(func.count())
                .select_from(TrackedItemRecord)
                .where(TrackedItemRecord.active.is_(True))
            )
            snaps_count = session.scalar(
                select(func.count()).select_from(PriceSnapshotRecord)
            )
            last_ts = session.scalar(select(func.max(PriceSnapshotRecord.recorded_at)))
            return PriceHistoryStats(
                tracked_items_count=int(items_count or 0),
                total_snapshots=int(snaps_count or 0),
                last_recorded_at=last_ts.strftime("%Y-%m-%d %H:%M:%S")
                if isinstance(last_ts, datetime)
                else (str(last_ts) if last_ts is not None else None),
            )

    def close(self) -> None:
        """Dispose SQLAlchemy engine connection pool."""
        self.engine.dispose()
