from decimal import Decimal
from app.models.enums import PriceAdvantage, StoreType
from app.models.product import StoreProduct
from app.services.matcher import ProductMatchingService


def test_product_matching_similarity() -> None:
    score = ProductMatchingService.compute_similarity("Jihočeské máslo 250g", "Madeta Jihočeské máslo 250g")
    assert score > 0.6


def test_compare_products_rohlik_cheaper(
    sample_rohlik_butter: StoreProduct,
    sample_kosik_butter: StoreProduct,
) -> None:
    matcher = ProductMatchingService()
    pair = matcher.compare_products("butter", "máslo", sample_rohlik_butter, sample_kosik_butter)

    assert pair.advantage == PriceAdvantage.ROHLIK_CHEAPER
    assert pair.cheaper_store == StoreType.ROHLIK
    # Comparison is now based on unit price (per kg/l): 239.60 - 211.60 = 28.00
    assert pair.price_difference == Decimal("28.00")
    assert pair.percentage_savings > Decimal("10.0")


def test_compare_products_tie(sample_rohlik_butter: StoreProduct) -> None:
    matcher = ProductMatchingService()
    # Identical price
    pair = matcher.compare_products("butter", "máslo", sample_rohlik_butter, sample_rohlik_butter)

    assert pair.advantage == PriceAdvantage.TIED
    assert pair.cheaper_store is None
    assert pair.price_difference == Decimal("0.00")
