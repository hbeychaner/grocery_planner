from decimal import Decimal
import pytest
from app.clients.rohlik import RohlikStoreClient
from app.models.enums import StoreType, UnitType


def test_rohlik_parse_product_normal() -> None:
    client = RohlikStoreClient()
    sample_item = {
        "productId": 1462148,
        "productName": "Miil Máslo 82%",
        "brand": "Miil",
        "price": {"full": 36.9, "currency": "Kč"},
        "originalPrice": {"full": 49.9},
        "pricePerUnit": {"full": 147.6, "currency": "Kč"},
        "unit": "kg",
        "textualAmount": "250 g",
        "link": "/1462148-miil-maslo-82",
        "imgPath": "/images/grocery/products/1462148/1462148.jpg",
        "inStock": True,
    }

    product = client._parse_product(sample_item)
    assert product is not None
    assert product.store == StoreType.ROHLIK
    assert product.product_id == "1462148"
    assert product.name == "Miil Máslo 82%"
    assert product.brand == "Miil"
    assert product.price == Decimal("36.9")
    assert product.original_price == Decimal("49.9")
    assert product.is_on_sale is True
    assert product.unit_price == Decimal("147.6")
    assert product.unit_type == UnitType.KILOGRAM
    assert product.url == "https://www.rohlik.cz/1462148-miil-maslo-82"
    assert "cdn.rohlik.cz" in product.image_url


def test_rohlik_parse_product_missing_required_fields() -> None:
    client = RohlikStoreClient()
    assert client._parse_product({}) is None
    assert client._parse_product({"productId": 123}) is None
    assert client._parse_product({"productName": "Only Name"}) is None


def test_rohlik_normalize_unit() -> None:
    client = RohlikStoreClient()
    assert client._normalize_unit("1 kg") == UnitType.KILOGRAM
    assert client._normalize_unit("500 g") == UnitType.GRAM
    assert client._normalize_unit("1 l") == UnitType.LITER
    assert client._normalize_unit("250 ml") == UnitType.MILLILITER
    assert client._normalize_unit("10 ks") == UnitType.PIECE
    assert client._normalize_unit("unknown") == UnitType.UNKNOWN
