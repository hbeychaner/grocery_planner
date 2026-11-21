from decimal import Decimal
import pytest
from app.clients.kosik import KosikStoreClient
from app.models.enums import StoreType, UnitType


def test_kosik_parse_product_normal() -> None:
    client = KosikStoreClient()
    sample_item = {
        "id": "13317",
        "name": "Tatra Farmářské máslo (84%)",
        "brand": {"name": "Tatra"},
        "price": 34.9,
        "recommendedPrice": 49.9,
        "isSale": True,
        "pricePerUnit": {"price": 174.5, "unit": "kg"},
        "unit": "ks",
        "url": "/p13317-tatra-farmarske-maslo-84",
        "image": "https://static-new.kosik.cz/images/thumbs/5w/WIDTHxHEIGHTx1_sample.jpg",
        "plannedStock": True,
    }

    product = client._parse_product(sample_item)
    assert product is not None
    assert product.store == StoreType.KOSIK
    assert product.product_id == "13317"
    assert product.name == "Tatra Farmářské máslo (84%)"
    assert product.brand == "Tatra"
    assert product.price == Decimal("34.9")
    assert product.original_price == Decimal("49.9")
    assert product.is_on_sale is True
    assert product.unit_price == Decimal("174.50")
    assert product.unit_type == UnitType.KILOGRAM
    assert product.url == "https://www.kosik.cz/p13317-tatra-farmarske-maslo-84"
    assert "200x200" in product.image_url


def test_kosik_parse_product_missing_required_fields() -> None:
    client = KosikStoreClient()
    assert client._parse_product({}) is None
    assert client._parse_product({"id": 123}) is None
    assert client._parse_product({"name": "Only Name"}) is None


def test_kosik_normalize_unit() -> None:
    client = KosikStoreClient()
    assert client._normalize_unit("kg") == UnitType.KILOGRAM
    assert client._normalize_unit("g") == UnitType.GRAM
    assert client._normalize_unit("l") == UnitType.LITER
    assert client._normalize_unit("ml") == UnitType.MILLILITER
    assert client._normalize_unit("ks") == UnitType.PIECE
    assert client._normalize_unit("unknown") == UnitType.UNKNOWN
