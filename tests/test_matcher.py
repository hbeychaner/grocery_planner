from decimal import Decimal
from app.models.enums import PriceAdvantage, StoreType, UnitType
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


def test_filter_relevant_products_nlp() -> None:
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
    prod_apple = StoreProduct(
        store=StoreType.KOSIK,
        product_id="3",
        name="Červená jablka Gala 1kg",
        price=Decimal("39.90"),
        in_stock=True,
        url="http://test",
    )

    filtered = matcher._filter_relevant_products("Banány 1kg", [prod_banana, prod_kiwi, prod_apple], query="bananas")
    assert prod_banana in filtered
    assert prod_kiwi not in filtered  # Irrelevant item rejected by NLP
    assert prod_apple not in filtered  # Irrelevant item rejected by NLP


def test_similarity_ignores_unit_and_number_overlap() -> None:
    # "Kiwi, 1 ks" and "Banán 1 ks" only share "1 ks"
    score = ProductMatchingService.compute_similarity("Kiwi, 1 ks", "Banán 1 ks")
    assert score < 0.3


def test_filter_excludes_brand_collision_false_positives() -> None:
    matcher = ProductMatchingService()
    fresh_avocado = StoreProduct(
        store=StoreType.ROHLIK,
        product_id="av1",
        name="Avokádo Hass malé 1 ks",
        brand=None,
        price=Decimal("36.90"),
        unit_type=UnitType.KILOGRAM,
        unit_price=Decimal("217.06"),
        in_stock=True,
    )
    mustard_brand_avokado = StoreProduct(
        store=StoreType.ROHLIK,
        product_id="av2",
        name="Avokádo Medová hořčice",
        brand="Avokádo",
        price=Decimal("41.90"),
        unit_type=UnitType.KILOGRAM,
        unit_price=Decimal("135.16"),
        in_stock=True,
    )
    filtered = matcher._filter_relevant_products(
        "avokádo", [fresh_avocado, mustard_brand_avokado], "avocado"
    )
    assert [p.product_id for p in filtered] == ["av1"]


def test_filter_enforces_multi_lemma_coverage_and_dominant_unit() -> None:
    matcher = ProductMatchingService()
    cider_vinegar_1 = StoreProduct(
        store=StoreType.KOSIK,
        product_id="v1",
        name="Bzenecký ocet kvasný jablečný 5%",
        price=Decimal("64.90"),
        unit_type=UnitType.LITER,
        unit_price=Decimal("64.90"),
        in_stock=True,
    )
    cider_vinegar_2 = StoreProduct(
        store=StoreType.KOSIK,
        product_id="v2",
        name="Metro Chef Ocet jablečný",
        price=Decimal("47.90"),
        unit_type=UnitType.LITER,
        unit_price=Decimal("95.80"),
        in_stock=True,
    )
    plain_vinegar = StoreProduct(
        store=StoreType.ROHLIK,
        product_id="v3",
        name="Kitchin Ocet kvasný lihový 8%",
        price=Decimal("12.90"),
        unit_type=UnitType.LITER,
        unit_price=Decimal("12.90"),
        in_stock=True,
    )
    vinegar_tablets = StoreProduct(
        store=StoreType.KOSIK,
        product_id="v4",
        name="MedPharma Jablečný ocet 107 tablet",
        price=Decimal("161.00"),
        unit_type=UnitType.PIECE,
        unit_price=Decimal("1.50"),
        in_stock=True,
    )

    filtered = matcher._filter_relevant_products(
        "jablečný ocet",
        [cider_vinegar_1, cider_vinegar_2, plain_vinegar, vinegar_tablets],
        "apple cider vinegar",
    )
    assert [p.product_id for p in filtered] == ["v1", "v2"]


def test_find_best_pair_uses_best_unit_price_on_tie() -> None:
    matcher = ProductMatchingService()
    r_best = StoreProduct(
        store=StoreType.ROHLIK,
        product_id="r1",
        name="Pilsner Urquell pivo ležák světlý",
        brand="Pilsner Urquell",
        price=Decimal("31.90"),
        unit_price=Decimal("63.80"),
        unit_type=UnitType.LITER,
        quantity=Decimal("0.5"),
        in_stock=True,
    )
    r_other = StoreProduct(
        store=StoreType.ROHLIK,
        product_id="r2",
        name="Pilsner Urquell plech 6x0.5l",
        brand="Pilsner Urquell",
        price=Decimal("264.00"),
        unit_price=Decimal("88.00"),
        unit_type=UnitType.LITER,
        quantity=Decimal("3.0"),
        in_stock=True,
    )
    k_best = StoreProduct(
        store=StoreType.KOSIK,
        product_id="k1",
        name="Pilsner Urquell světlý ležák, sklo",
        brand="Pilsner Urquell",
        price=Decimal("31.90"),
        unit_price=Decimal("63.80"),
        unit_type=UnitType.LITER,
        quantity=Decimal("0.5"),
        in_stock=True,
    )
    k_other = StoreProduct(
        store=StoreType.KOSIK,
        product_id="k2",
        name="Pilsner Urquell plech 6x0.5l",
        brand="Pilsner Urquell",
        price=Decimal("286.74"),
        unit_price=Decimal("95.58"),
        unit_type=UnitType.LITER,
        quantity=Decimal("3.0"),
        in_stock=True,
    )

    pair = matcher.find_best_pair(
        "pilsner urquell",
        "pilsner urquell",
        [r_other, r_best],
        [k_other, k_best],
    )
    assert pair is not None
    assert pair.rohlik_product.product_id == "r1"
    assert pair.kosik_product.product_id == "k1"
    assert pair.advantage == PriceAdvantage.TIED
    assert pair.price_difference == Decimal("0.00")
