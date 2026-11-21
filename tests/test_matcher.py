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


def test_confidence_clamping(sample_rohlik_butter: StoreProduct, sample_kosik_butter: StoreProduct) -> None:
    matcher = ProductMatchingService()
    # Over 1.0 confidence should be clamped to 1.0 and not raise ValidationError
    pair = matcher.compare_products("butter", "máslo", sample_rohlik_butter, sample_kosik_butter, confidence=1.3)
    assert pair.match_confidence == 1.0

    # Under 0.0 confidence should be clamped to 0.0
    pair2 = matcher.compare_products("butter", "máslo", sample_rohlik_butter, sample_kosik_butter, confidence=-0.5)
    assert pair2.match_confidence == 0.0


def test_filter_relevant_products_stemming() -> None:
    matcher = ProductMatchingService()
    prod_banana = StoreProduct(
        store=StoreType.ROHLIK,
        product_id="1",
        name="Banán 1 ks",
        price=Decimal("6.50"),
        in_stock=True,
        url="http://test",
    )
    prod_kiwi = StoreProduct(
        store=StoreType.KOSIK,
        product_id="2",
        name="Kiwi, 1 ks",
        price=Decimal("19.90"),
        in_stock=True,
        url="http://test",
    )
    prod_bread = StoreProduct(
        store=StoreType.KOSIK,
        product_id="3",
        name="Koláčkova pekárna Banana bread bez lepku",
        price=Decimal("69.90"),
        in_stock=True,
        url="http://test",
    )

    filtered = matcher._filter_relevant_products("Banány 1kg", [prod_banana, prod_kiwi, prod_bread], query="bananas")
    assert prod_banana in filtered
    assert prod_kiwi not in filtered  # Irrelevant stem
    assert prod_bread not in filtered  # Excluded bakery keyword


def test_similarity_ignores_unit_and_number_overlap() -> None:
    # "Kiwi, 1 ks" and "Banán 1 ks" only share "1 ks"
    score = ProductMatchingService.compute_similarity("Kiwi, 1 ks", "Banán 1 ks")
    assert score < 0.3
