from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from httpx import ASGITransport, AsyncClient

from sqlalchemy.orm import Session

from app.main import app
from app.models.comparison import ComparisonResponse, MatchedProductPair
from app.models.enums import PriceAdvantage, StoreType, UnitType
from app.models.product import StoreProduct
from app.services.price_history import PriceHistoryService, PriceSnapshotRecord
from app.services.tracker_runner import PriceTrackerRunner


def _make_comparison(query: str, r_unit_price: str, k_unit_price: str) -> ComparisonResponse:
    r_prod = StoreProduct(
        store=StoreType.ROHLIK,
        product_id="r1",
        name=f"Rohlik {query}",
        price=Decimal("40.00"),
        unit_type=UnitType.KILOGRAM,
        unit_price=Decimal(r_unit_price),
        in_stock=True,
    )
    k_prod = StoreProduct(
        store=StoreType.KOSIK,
        product_id="k1",
        name=f"Kosik {query}",
        price=Decimal("45.00"),
        unit_type=UnitType.KILOGRAM,
        unit_price=Decimal(k_unit_price),
        in_stock=True,
    )
    pair = MatchedProductPair(
        query=query,
        query_cs=query,
        rohlik_product=r_prod,
        kosik_product=k_prod,
        advantage=PriceAdvantage.ROHLIK_CHEAPER,
        cheaper_store=StoreType.ROHLIK,
        price_difference=Decimal("10.00"),
        percentage_savings=Decimal("10.0"),
    )
    return ComparisonResponse(
        query=query,
        query_translated=query,
        advantage=PriceAdvantage.ROHLIK_CHEAPER,
        cheapest_store=StoreType.ROHLIK,
        price_difference=Decimal("10.00"),
        percentage_savings=Decimal("10.0"),
        voice_summary_en="test",
        voice_summary_cs="test",
        primary_pair=pair,
        rohlik_ranked=[r_prod],
        kosik_ranked=[k_prod],
        category="dairy",
    )


def test_price_history_service_records_and_queries_series() -> None:
    history = PriceHistoryService(db_path=Path(":memory:"))
    history.add_tracked_item("butter", query_cs="máslo", category="dairy")

    t1 = datetime.now(timezone.utc) - timedelta(days=35)
    t2 = datetime.now(timezone.utc)

    history.record_comparison(_make_comparison("butter", "210.00", "235.00"), recorded_at=t1)
    history.record_comparison(_make_comparison("butter", "199.00", "240.00"), recorded_at=t2)

    series = history.get_item_history("butter", days=90)
    assert series.query == "butter"
    assert series.unit_type == "kg"
    assert len(series.rohlik_series) == 2
    assert len(series.kosik_series) == 2
    assert series.rohlik_series[0].unit_price == 210.0
    assert series.rohlik_series[1].unit_price == 199.0

    items = history.list_tracked_items()
    assert len(items) == 1
    assert items[0].latest_rohlik_unit_price == 199.0
    assert items[0].latest_kosik_unit_price == 240.0
    history.close()


@pytest.mark.asyncio
async def test_tracker_runner_sweeps_watchlist() -> None:
    history = PriceHistoryService(db_path=Path(":memory:"))
    history.add_tracked_item("butter")
    history.add_tracked_item("milk")

    mock_comparator = AsyncMock()
    mock_comparator.compare_single_item.side_effect = [
        _make_comparison("butter", "200.00", "220.00"),
        _make_comparison("milk", "25.00", "29.00"),
    ]

    runner = PriceTrackerRunner(
        comparator=mock_comparator,
        history=history,
        concurrency=2,
        delay_between_requests=0.0,
    )
    result = await runner.run()
    assert result.total_items == 2
    assert result.succeeded == 2
    assert result.failed == 0
    assert result.snapshots_recorded == 4
    history.close()


@pytest.mark.asyncio
async def test_trends_page_and_history_endpoints() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        trends_resp = await ac.get("/trends")
        assert trends_resp.status_code == 200
        assert "Weekly Grocery Price Trends" in trends_resp.text

        items_resp = await ac.get("/api/v1/history/items")
        assert items_resp.status_code == 200
        data = items_resp.json()
        assert data["stats"]["tracked_items_count"] > 0

        analytics_resp = await ac.get("/api/v1/history/analytics")
        assert analytics_resp.status_code == 200
        analytics = analytics_resp.json()
        assert analytics["overall"]["category"] == "overall"
        assert len(analytics["categories"]) > 0

        cat_series_resp = await ac.get("/api/v1/history/analytics/series?category=overall&days=90")
        assert cat_series_resp.status_code == 200
        cat_series = cat_series_resp.json()
        assert cat_series["category"] == "overall"


def test_price_history_separates_bio_and_regular_series() -> None:
    history = PriceHistoryService(db_path=Path(":memory:"))
    history.add_tracked_item("gala apples", query_cs="jablka gala", category="produce")

    reg_r = StoreProduct(
        store=StoreType.ROHLIK,
        product_id="r_reg",
        name="Jablka Gala 1 kg",
        price=Decimal("44.90"),
        unit_type=UnitType.KILOGRAM,
        unit_price=Decimal("44.90"),
        in_stock=True,
    )
    bio_r = StoreProduct(
        store=StoreType.ROHLIK,
        product_id="r_bio",
        name="BIO Jablka Gala 600g",
        price=Decimal("79.90"),
        unit_type=UnitType.KILOGRAM,
        unit_price=Decimal("133.17"),
        in_stock=True,
    )
    reg_k = StoreProduct(
        store=StoreType.KOSIK,
        product_id="k_reg",
        name="Sady Životice Jablka Gala",
        price=Decimal("37.45"),
        unit_type=UnitType.KILOGRAM,
        unit_price=Decimal("37.45"),
        in_stock=True,
    )
    comp = ComparisonResponse(
        query="gala apples",
        query_translated="jablka gala",
        advantage=PriceAdvantage.KOSIK_CHEAPER,
        cheapest_store=StoreType.KOSIK,
        price_difference=Decimal("7.45"),
        percentage_savings=Decimal("16.6"),
        voice_summary_en="test",
        voice_summary_cs="test",
        rohlik_candidates=[reg_r, bio_r],
        kosik_candidates=[reg_k],
        rohlik_ranked=[reg_r],
        kosik_ranked=[reg_k],
        category="produce",
    )
    recorded = history.record_comparison(comp)
    assert recorded == 3

    series = history.get_item_history("gala apples")
    assert len(series.rohlik_series) == 1
    assert series.rohlik_series[0].is_bio is False
    assert series.rohlik_series[0].unit_price == 44.9
    assert len(series.rohlik_bio_series) == 1
    assert series.rohlik_bio_series[0].is_bio is True
    assert series.rohlik_bio_series[0].unit_price == 133.17
    assert len(series.kosik_series) == 1
    assert len(series.kosik_bio_series) == 0
    history.close()


def test_csu_bls_matched_basket_analytics_and_series() -> None:
    """ČSÚ vs. US BLS averages must only include items present in BOTH sources."""
    history = PriceHistoryService(db_path=Path(":memory:"))
    history.add_tracked_item("plain flour", query_cs="hladká mouka", category="baking")
    history.add_tracked_item("honey", query_cs="med", category="baking")
    history.add_tracked_item("pilsner urquell", query_cs="pilsner urquell", category="alcohol")

    ts = datetime(2026, 3, 1, tzinfo=timezone.utc)
    with Session(history.engine) as session:
        session.add_all(
            [
                PriceSnapshotRecord(
                    item_query="plain flour",
                    store="csu",
                    product_name="ČSÚ plain flour",
                    price=20.0,
                    unit_price=20.0,
                    unit_type="kg",
                    recorded_at=ts,
                ),
                PriceSnapshotRecord(
                    item_query="plain flour",
                    store="bls",
                    product_name="BLS plain flour",
                    price=30.0,
                    unit_price=30.0,
                    unit_type="kg",
                    recorded_at=ts,
                ),
                # honey is only in ČSÚ, not in BLS — must be excluded from ČSÚ vs. BLS average
                PriceSnapshotRecord(
                    item_query="honey",
                    store="csu",
                    product_name="ČSÚ honey",
                    price=250.0,
                    unit_price=250.0,
                    unit_type="kg",
                    recorded_at=ts,
                ),
                # pilsner urquell is only in ČSÚ under alcohol — avg_csu/avg_bls should both be None
                PriceSnapshotRecord(
                    item_query="pilsner urquell",
                    store="csu",
                    product_name="ČSÚ pilsner urquell",
                    price=60.0,
                    unit_price=60.0,
                    unit_type="l",
                    recorded_at=ts,
                ),
            ]
        )
        session.commit()

    analytics = history.get_category_analytics()
    by_cat = {row.category: row for row in analytics.categories}
    assert by_cat["baking"].avg_csu_unit_price == 20.0
    assert by_cat["baking"].avg_bls_unit_price == 30.0
    assert by_cat["alcohol"].display_name == "Alcoholic Beverages"
    assert by_cat["alcohol"].avg_csu_unit_price is None
    assert by_cat["alcohol"].avg_bls_unit_price is None
    assert analytics.overall.avg_csu_unit_price == 20.0
    assert analytics.overall.avg_bls_unit_price == 30.0

    baking_series = history.get_category_series("baking", days=3650)
    assert len(baking_series.points) == 1
    assert baking_series.points[0].avg_csu == 20.0
    assert baking_series.points[0].avg_bls == 30.0

    alcohol_series = history.get_category_series("alcohol", days=3650)
    assert len(alcohol_series.points) == 1
    assert alcohol_series.points[0].avg_csu is None
    assert alcohol_series.points[0].avg_bls is None
    history.close()
