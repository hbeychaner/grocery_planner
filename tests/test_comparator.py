from decimal import Decimal
import pytest
from app.models.enums import PriceAdvantage, StoreType
from app.models.comparison import BasketComparisonItem
from app.models.product import StoreProduct
from app.services.comparator import PriceComparisonService
from tests.conftest import MockStoreClient


@pytest.mark.asyncio
async def test_compare_single_item(
    sample_rohlik_butter: StoreProduct,
    sample_kosik_butter: StoreProduct,
) -> None:
    r_client = MockStoreClient(StoreType.ROHLIK, [sample_rohlik_butter])
    k_client = MockStoreClient(StoreType.KOSIK, [sample_kosik_butter])

    service = PriceComparisonService(rohlik_client=r_client, kosik_client=k_client)
    res = await service.compare_single_item("butter")

    assert res.advantage == PriceAdvantage.ROHLIK_CHEAPER
    assert res.cheapest_store == StoreType.ROHLIK
    # price_difference is now based on unit price (per kg/l): 239.60 - 211.60 = 28.00
    assert res.price_difference == Decimal("28.00")
    assert "Rohlik offers the best value for butter" in res.voice_summary_en


@pytest.mark.asyncio
async def test_compare_basket(
    sample_rohlik_butter: StoreProduct,
    sample_kosik_butter: StoreProduct,
) -> None:
    r_client = MockStoreClient(StoreType.ROHLIK, [sample_rohlik_butter])
    k_client = MockStoreClient(StoreType.KOSIK, [sample_kosik_butter])

    service = PriceComparisonService(rohlik_client=r_client, kosik_client=k_client)
    items = [BasketComparisonItem(query="butter", quantity=2)]

    res = await service.compare_basket(items)

    assert res.total_rohlik == Decimal("105.80")
    assert res.total_kosik == Decimal("119.80")
    assert res.advantage == PriceAdvantage.ROHLIK_CHEAPER
    assert res.savings == Decimal("14.00")
