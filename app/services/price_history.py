import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, create_engine, func, inspect, select, text, update
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
    is_bio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    is_bio: bool = False
    recorded_at: str


class ItemPriceHistory(BaseModel):
    """Time-series price history for a grocery item across both stores (Regular vs. BIO) + ČSÚ benchmark."""

    query: str
    unit_type: str = "kg"
    rohlik_series: List[PriceSnapshotPoint] = Field(default_factory=list)
    kosik_series: List[PriceSnapshotPoint] = Field(default_factory=list)
    rohlik_bio_series: List[PriceSnapshotPoint] = Field(default_factory=list)
    kosik_bio_series: List[PriceSnapshotPoint] = Field(default_factory=list)
    csu_series: List[PriceSnapshotPoint] = Field(default_factory=list)
    bls_series: List[PriceSnapshotPoint] = Field(default_factory=list)


class PriceHistoryStats(BaseModel):
    """Summary metrics for the price tracking database."""

    tracked_items_count: int
    total_snapshots: int
    last_recorded_at: Optional[str] = None


class CategoryAnalyticsRow(BaseModel):
    """Aggregated unit-price & weekly inflation metrics for a category or overall."""

    category: str
    display_name: str
    item_count: int
    avg_rohlik_unit_price: Optional[float] = None
    avg_kosik_unit_price: Optional[float] = None
    blended_avg_unit_price: Optional[float] = None
    avg_bio_unit_price: Optional[float] = None
    avg_csu_unit_price: Optional[float] = None
    avg_bls_unit_price: Optional[float] = None
    wow_change_pct: Optional[float] = None


class CategoryAnalyticsResponse(BaseModel):
    """Overall and per-category inflation analytics table."""

    overall: CategoryAnalyticsRow
    categories: List[CategoryAnalyticsRow] = Field(default_factory=list)


class CategorySeriesPoint(BaseModel):
    """Single timestamp point for overall/category average price trend."""

    recorded_at: str
    avg_rohlik: Optional[float] = None
    avg_kosik: Optional[float] = None
    blended_avg: Optional[float] = None
    avg_bio: Optional[float] = None
    avg_csu: Optional[float] = None
    avg_bls: Optional[float] = None


class CategoryHistorySeries(BaseModel):
    """Time-series average unit prices for a category or overall."""

    category: str
    display_name: str
    points: List[CategorySeriesPoint] = Field(default_factory=list)


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
        self._ensure_columns()

    def _ensure_columns(self) -> None:
        """Safely add new columns to existing SQLite databases."""
        insp = inspect(self.engine)
        cols = {c["name"] for c in insp.get_columns("price_snapshots")}
        if "is_bio" not in cols:
            with self.engine.begin() as conn:
                conn.execute(text("ALTER TABLE price_snapshots ADD COLUMN is_bio BOOLEAN NOT NULL DEFAULT 0"))

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
            stmt = sqlite_insert(TrackedItemRecord).values(values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["query"],
                set_={
                    "query_cs": func.coalesce(stmt.excluded.query_cs, TrackedItemRecord.query_cs),
                    "category": func.coalesce(stmt.excluded.category, TrackedItemRecord.category),
                },
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
                    PriceSnapshotRecord.is_bio.is_(False),
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
                    PriceSnapshotRecord.is_bio.is_(False),
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
        """Persist best-value regular AND BIO/organic unit prices for both stores."""
        from app.services.matcher import ProductMatchingService

        norm = self._normalize_query(comparison.query)
        ts = recorded_at or datetime.now(timezone.utc)

        def _pick_regular_and_bio(
            ranked: List[StoreProduct],
            candidates: List[StoreProduct],
            pair_fallback: Optional[StoreProduct],
        ) -> List[tuple[StoreProduct, bool]]:
            picked: List[tuple[StoreProduct, bool]] = []
            # Best regular product from ranked list
            reg = next((p for p in ranked if not ProductMatchingService.is_organic(p.name)), None)
            if reg is None and pair_fallback and not ProductMatchingService.is_organic(pair_fallback.name):
                reg = pair_fallback
            if reg is not None:
                picked.append((reg, False))

            # Best BIO/organic product from relevant candidates (matching query + unit_type if regular exists)
            bio_candidates = [
                p for p in candidates if ProductMatchingService.is_organic(p.name)
            ]
            if bio_candidates:
                if reg is not None and reg.unit_type:
                    same_unit_bio = [p for p in bio_candidates if p.unit_type == reg.unit_type]
                    if same_unit_bio:
                        bio_candidates = same_unit_bio
                # Use matcher's relevance & ranking so we don't pick unrelated BIO items
                relevant_bio = ProductMatchingService()._filter_relevant_products(
                    comparison.query_translated,
                    bio_candidates,
                    comparison.query,
                )
                pool = relevant_bio if relevant_bio else []
                if pool:
                    best_bio = min(
                        pool,
                        key=lambda p: p.unit_price if (p.unit_price and p.unit_price > 0) else p.price,
                    )
                    picked.append((best_bio, True))

            # If no regular product existed at all, record pair_fallback if it was BIO
            if reg is None and not picked and pair_fallback is not None:
                picked.append((pair_fallback, ProductMatchingService.is_organic(pair_fallback.name)))

            return picked

        r_picks = _pick_regular_and_bio(
            comparison.rohlik_ranked,
            comparison.rohlik_candidates,
            comparison.primary_pair.rohlik_product if comparison.primary_pair else None,
        )
        k_picks = _pick_regular_and_bio(
            comparison.kosik_ranked,
            comparison.kosik_candidates,
            comparison.primary_pair.kosik_product if comparison.primary_pair else None,
        )

        snapshots: List[PriceSnapshotRecord] = []
        for store_name, picks in (("rohlik", r_picks), ("kosik", k_picks)):
            for prod, is_bio_flag in picks:
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
                        is_bio=is_bio_flag,
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
        """Retrieve time-series unit-price snapshots for plotting Regular vs BIO across stores."""
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
            rohlik_bio_series: List[PriceSnapshotPoint] = []
            kosik_bio_series: List[PriceSnapshotPoint] = []
            csu_series: List[PriceSnapshotPoint] = []
            bls_series: List[PriceSnapshotPoint] = []
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
                    is_bio=bool(row.is_bio),
                    recorded_at=ts_str,
                )
                if row.unit_type and not row.is_bio and row.store not in ("csu", "bls"):
                    detected_unit = row.unit_type
                elif row.unit_type and detected_unit == "kg":
                    detected_unit = row.unit_type

                if row.store == "rohlik":
                    (rohlik_bio_series if row.is_bio else rohlik_series).append(point)
                elif row.store == "kosik":
                    (kosik_bio_series if row.is_bio else kosik_series).append(point)
                elif row.store == "csu":
                    csu_series.append(point)
                elif row.store == "bls":
                    bls_series.append(point)

            return ItemPriceHistory(
                query=norm,
                unit_type=detected_unit,
                rohlik_series=rohlik_series,
                kosik_series=kosik_series,
                rohlik_bio_series=rohlik_bio_series,
                kosik_bio_series=kosik_bio_series,
                csu_series=csu_series,
                bls_series=bls_series,
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

    def get_category_analytics(self) -> CategoryAnalyticsResponse:
        """Compute overall and per-category average unit prices and weekly inflation %."""
        CATEGORY_LABELS = {
            "overall": "Overall (All Categories)",
            "fruits": "Fruits",
            "vegetables": "Vegetables",
            "goods": "Household & Personal Goods",
            "dairy": "Dairy",
            "dairy_eggs": "Eggs",
            "bakery": "Bakery",
            "meat": "Meat",
            "seafood": "Seafood",
            "pantry": "Grains, Rice & Pantry",
            "baking": "Baking Goods",
            "spices": "Spices & Seasonings",
            "desserts": "Desserts & Sweets",
            "beverages": "Beverages",
            "other": "Other",
        }
        PREFERRED_ORDER = [
            "fruits",
            "vegetables",
            "goods",
            "dairy",
            "dairy_eggs",
            "bakery",
            "meat",
            "seafood",
            "pantry",
            "baking",
            "spices",
            "desserts",
            "beverages",
        ]

        with Session(self.engine) as session:
            item_rows = session.execute(
                select(TrackedItemRecord.query, TrackedItemRecord.category).where(
                    TrackedItemRecord.active.is_(True)
                )
            ).all()
            item_cats: Dict[str, str] = {
                r[0]: (r[1] or "other") for r in item_rows
            }

            snap_rows = session.scalars(
                select(PriceSnapshotRecord)
                .where(PriceSnapshotRecord.unit_price.is_not(None))
                .order_by(PriceSnapshotRecord.recorded_at.desc(), PriceSnapshotRecord.id.desc())
            ).all()

        # Group snapshots by (item_query, store, is_bio) ordered newest -> oldest
        grouped: Dict[tuple[str, str, bool], List[float]] = {}
        for s in snap_rows:
            if s.item_query not in item_cats or s.unit_price is None:
                continue
            key = (s.item_query, s.store, bool(s.is_bio))
            grouped.setdefault(key, []).append(float(s.unit_price))

        def _build_row(cat_key: str, queries_in_cat: List[str]) -> CategoryAnalyticsRow:
            q_set = set(queries_in_cat)
            r_latest: List[float] = []
            k_latest: List[float] = []
            bio_latest: List[float] = []
            csu_latest: List[float] = []
            bls_latest: List[float] = []
            curr_all: List[float] = []
            prev_all: List[float] = []

            items_with_data = set()
            for (q, store, is_bio), prices in grouped.items():
                if q not in q_set:
                    continue
                items_with_data.add(q)
                latest_p = prices[0]
                if store == "csu":
                    csu_latest.append(latest_p)
                elif store == "bls":
                    bls_latest.append(latest_p)
                elif is_bio:
                    bio_latest.append(latest_p)
                else:
                    if store == "rohlik":
                        r_latest.append(latest_p)
                    elif store == "kosik":
                        k_latest.append(latest_p)
                    if len(prices) >= 2:
                        curr_all.append(latest_p)
                        prev_all.append(prices[1])

            blended_pool = r_latest + k_latest
            wow_pct: Optional[float] = None
            if prev_all and sum(prev_all) > 0:
                avg_prev = sum(prev_all) / len(prev_all)
                avg_curr = sum(curr_all) / len(curr_all)
                wow_pct = round(((avg_curr - avg_prev) / avg_prev) * 100, 2)

            return CategoryAnalyticsRow(
                category=cat_key,
                display_name=CATEGORY_LABELS.get(cat_key, cat_key.replace("_", " ").title()),
                item_count=len(items_with_data) if items_with_data else len(queries_in_cat),
                avg_rohlik_unit_price=round(sum(r_latest) / len(r_latest), 2) if r_latest else None,
                avg_kosik_unit_price=round(sum(k_latest) / len(k_latest), 2) if k_latest else None,
                blended_avg_unit_price=round(sum(blended_pool) / len(blended_pool), 2) if blended_pool else None,
                avg_bio_unit_price=round(sum(bio_latest) / len(bio_latest), 2) if bio_latest else None,
                avg_csu_unit_price=round(sum(csu_latest) / len(csu_latest), 2) if csu_latest else None,
                avg_bls_unit_price=round(sum(bls_latest) / len(bls_latest), 2) if bls_latest else None,
                wow_change_pct=wow_pct,
            )

        all_queries = list(item_cats.keys())
        overall_row = _build_row("overall", all_queries)

        by_cat: Dict[str, List[str]] = {}
        for q, c in item_cats.items():
            by_cat.setdefault(c, []).append(q)

        ordered_cats = [c for c in PREFERRED_ORDER if c in by_cat] + sorted(
            c for c in by_cat if c not in PREFERRED_ORDER
        )
        category_rows = [_build_row(c, by_cat[c]) for c in ordered_cats]
        return CategoryAnalyticsResponse(overall=overall_row, categories=category_rows)

    def get_category_series(self, category: str = "overall", days: int = 90) -> CategoryHistorySeries:
        """Compute time-series average unit prices for a category (or overall) across sweeps."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cat_norm = (category or "overall").strip().lower()

        with Session(self.engine) as session:
            item_rows = session.execute(
                select(TrackedItemRecord.query, TrackedItemRecord.category).where(
                    TrackedItemRecord.active.is_(True)
                )
            ).all()
            allowed_queries = {
                r[0]
                for r in item_rows
                if cat_norm == "overall" or (r[1] or "other") == cat_norm
            }

            if not allowed_queries:
                return CategoryHistorySeries(
                    category=cat_norm,
                    display_name=cat_norm.replace("_", " ").title(),
                    points=[],
                )

            snap_rows = session.scalars(
                select(PriceSnapshotRecord)
                .where(
                    PriceSnapshotRecord.item_query.in_(allowed_queries),
                    PriceSnapshotRecord.unit_price.is_not(None),
                    PriceSnapshotRecord.recorded_at >= cutoff,
                )
                .order_by(PriceSnapshotRecord.recorded_at.asc(), PriceSnapshotRecord.id.asc())
            ).all()

        # Bucket snapshots by date (YYYY-MM-DD HH:MM) so each sweep forms one clean point
        buckets: Dict[str, Dict[str, List[float]]] = {}
        for s in snap_rows:
            if s.unit_price is None:
                continue
            ts_bucket = (
                s.recorded_at.strftime("%Y-%m-%d %H:%M")
                if isinstance(s.recorded_at, datetime)
                else str(s.recorded_at)[:16]
            )
            b = buckets.setdefault(ts_bucket, {"rohlik": [], "kosik": [], "bio": [], "csu": [], "bls": []})
            val = float(s.unit_price)
            if s.store == "csu":
                b["csu"].append(val)
            elif s.store == "bls":
                b["bls"].append(val)
            elif s.is_bio:
                b["bio"].append(val)
            elif s.store == "rohlik":
                b["rohlik"].append(val)
            elif s.store == "kosik":
                b["kosik"].append(val)

        points: List[CategorySeriesPoint] = []
        for ts_key in sorted(buckets.keys()):
            b = buckets[ts_key]
            r_vals = b["rohlik"]
            k_vals = b["kosik"]
            bio_vals = b["bio"]
            csu_vals = b["csu"]
            bls_vals = b["bls"]
            blended_vals = r_vals + k_vals
            points.append(
                CategorySeriesPoint(
                    recorded_at=ts_key,
                    avg_rohlik=round(sum(r_vals) / len(r_vals), 2) if r_vals else None,
                    avg_kosik=round(sum(k_vals) / len(k_vals), 2) if k_vals else None,
                    blended_avg=round(sum(blended_vals) / len(blended_vals), 2) if blended_vals else None,
                    avg_bio=round(sum(bio_vals) / len(bio_vals), 2) if bio_vals else None,
                    avg_csu=round(sum(csu_vals) / len(csu_vals), 2) if csu_vals else None,
                    avg_bls=round(sum(bls_vals) / len(bls_vals), 2) if bls_vals else None,
                )
            )

        display = "Overall (All Categories)" if cat_norm == "overall" else cat_norm.replace("_", " ").title()
        return CategoryHistorySeries(category=cat_norm, display_name=display, points=points)

    def close(self) -> None:
        """Dispose SQLAlchemy engine connection pool."""
        self.engine.dispose()
