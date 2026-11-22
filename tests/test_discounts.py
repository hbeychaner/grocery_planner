from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.clients.rohlik import RohlikStoreClient
from app.main import app
from app.api.deps import get_comparison_service, get_price_history_service
from app.models.enums import StoreType, UnitType
from app.models.product import ProductSale, StoreProduct
from app.services.price_history import TrackedItem


def test_rohlik_parse_product_applies_premium_sale_and_keeps_all_sales() -> None:
    client = RohlikStoreClient()
    raw_item = {
        "productId": 1482618,
        "productName": "Miil Německé Máslo jemně kyselé",
        "brand": "Miil",
        "unit": "kg",
        "textualAmount": "250 g",
        "price": {"full": 44.9},
        "pricePerUnit": {"full": 179.6},
        "originalPrice": {"full": 0},
        "link": "?productPopup=1482618-miil-nemecke-maslo-jemne-kysele",
        "inStock": True,
        "sales": [
            {
                "id": 15658360,
                "type": "expiration",
                "remaining": 203,
                "price": {"full": 33.67},
                "priceForUnit": {"full": 134.68},
                "originalPrice": {"full": 44.9},
                "discountPercentage": 25,
                "startedAt": "2026-11-21 22:38:03",
                "endsAt": "2026-11-24 23:59:59",
                "active": True,
                "welcomePrice": False,
                "silent": False,
            },
            {
                "id": 14634429,
                "type": "premium",
                "remaining": 697,
                "price": {"full": 40.41},
                "priceForUnit": {"full": 161.64},
                "originalPrice": {"full": 44.9},
                "discountPercentage": 10,
                "startedAt": "2026-07-02 02:30:57",
                "endsAt": None,
                "active": True,
                "welcomePrice": True,
                "silent": False,
            },
        ],
    }

    parsed = client._parse_product(raw_item)
    assert parsed is not None
    # Effective price uses the non-expiration 'premium' sale (40.41 CZK), not 44.90 or 33.67 clearance
    assert parsed.price == Decimal("40.41")
    assert parsed.original_price == Decimal("44.9")
    assert parsed.unit_price == Decimal("161.64")
    assert parsed.is_on_sale is True
    assert parsed.discount_percentage == 10
    assert parsed.sale_type == "premium"
    # Both active sales are retained for the Discount Tracker
    assert len(parsed.sales) == 2
    assert {s.sale_type for s in parsed.sales} == {"expiration", "premium"}


def test_discounts_endpoint_filters_expiration_and_store() -> None:
    rohlik_item = StoreProduct(
        store=StoreType.ROHLIK,
        product_id="1482618",
        name="Miil Německé Máslo",
        price=Decimal("40.41"),
        original_price=Decimal("44.90"),
        is_on_sale=True,
        discount_percentage=10,
        sale_type="premium",
        unit_type=UnitType.KILOGRAM,
        unit_price=Decimal("161.64"),
        sales=[
            ProductSale(
                sale_type="expiration",
                price=Decimal("33.67"),
                original_price=Decimal("44.90"),
                discount_percentage=25,
                ends_at="2026-11-24 23:59:59",
                remaining=203,
            ),
            ProductSale(
                sale_type="premium",
                price=Decimal("40.41"),
                original_price=Decimal("44.90"),
                discount_percentage=10,
                welcome_price=True,
            ),
        ],
    )
    kosik_exp_only = StoreProduct(
        store=StoreType.KOSIK,
        product_id="k99",
        name="Košík Expiring Butter",
        price=Decimal("49.90"),
        is_on_sale=False,
        unit_type=UnitType.KILOGRAM,
        unit_price=Decimal("199.60"),
        sales=[
            ProductSale(
                sale_type="expiration",
                price=Decimal("30.00"),
                original_price=Decimal("49.90"),
                discount_percentage=40,
                ends_at="2026-11-23 23:59:59",
            )
        ],
    )

    mock_comp = MagicMock()
    mock_comp.rohlik_client = MagicMock()
    mock_comp.rohlik_client.search = AsyncMock(return_value=[rohlik_item])
    mock_comp.kosik_client = MagicMock()
    mock_comp.kosik_client.search = AsyncMock(return_value=[kosik_exp_only])

    mock_hist = MagicMock()
    mock_hist.list_tracked_items = MagicMock(
        return_value=[TrackedItem(query="butter", query_cs="máslo", category="dairy")]
    )

    app.dependency_overrides[get_comparison_service] = lambda: mock_comp
    app.dependency_overrides[get_price_history_service] = lambda: mock_hist
    try:
        client = TestClient(app)
        resp_all = client.get("/api/v1/discounts")
        assert resp_all.status_code == 200
        body_all = resp_all.json()
        assert body_all["total_discounts"] == 2
        assert body_all["items"][0]["best_sale"]["discount_percentage"] == 40

        resp_no_exp = client.get("/api/v1/discounts?include_expiration=false")
        assert resp_no_exp.status_code == 200
        body_no_exp = resp_no_exp.json()
        assert body_no_exp["total_discounts"] == 1
        assert body_no_exp["items"][0]["product"]["product_id"] == "1482618"
        assert body_no_exp["items"][0]["best_sale"]["sale_type"] == "premium"
    finally:
        app.dependency_overrides.clear()
