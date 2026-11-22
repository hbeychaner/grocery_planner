from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.clients.base import StoreSearchCache
from app.clients.kosik import KosikStoreClient
from app.clients.rohlik import RohlikStoreClient
from app.models.enums import StoreType, UnitType
from app.models.product import StoreProduct


def _make_product(store: StoreType, pid: str, name: str) -> StoreProduct:
    return StoreProduct(
        store=store,
        product_id=pid,
        name=name,
        price=Decimal("39.90"),
        unit_type=UnitType.KILOGRAM,
        unit_price=Decimal("159.60"),
    )


def test_store_search_cache_ttl_and_limit_slicing(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr("app.clients.base.time.monotonic", lambda: now[0])

    cache = StoreSearchCache(ttl_seconds=86400)
    items = [_make_product(StoreType.ROHLIK, str(i), f"Máslo {i}") for i in range(5)]
    cache.set("  Máslo ", 5, items)

    # Exact hit (whitespace/case normalized) and smaller limit reuse
    hit = cache.get("máslo", 3)
    assert hit is not None
    assert len(hit) == 3

    # Larger limit than cached misses so store can fetch more
    assert cache.get("máslo", 10) is None

    # After 24h TTL expires, entry is evicted
    now[0] += 86400.0
    assert cache.get("máslo", 5) is None


@pytest.mark.asyncio
async def test_rohlik_and_kosik_search_use_24h_cache() -> None:
    r_client = RohlikStoreClient()
    r_resp = MagicMock()
    r_resp.status_code = 200
    r_resp.json.return_value = {
        "data": {
            "productList": [
                {
                    "productId": 1,
                    "productName": "Máslo 250g",
                    "unit": "kg",
                    "textualAmount": "250 g",
                    "price": {"full": 44.9},
                    "pricePerUnit": {"full": 179.6},
                    "link": "/1-maslo",
                }
            ]
        }
    }
    mock_r_http = MagicMock()
    mock_r_http.get = AsyncMock(return_value=r_resp)
    mock_r_http.is_closed = False
    r_client._http_client = mock_r_http

    res1 = await r_client.search("máslo", limit=5)
    res2 = await r_client.search("máslo", limit=5)
    assert len(res1) == 1
    assert len(res2) == 1
    assert mock_r_http.get.await_count == 1

    # Bypassing cache triggers a fresh fetch
    await r_client.search("máslo", limit=5, use_cache=False)
    assert mock_r_http.get.await_count == 2

    k_client = KosikStoreClient()
    k_resp = MagicMock()
    k_resp.status_code = 200
    k_resp.json.return_value = {"response": {"results": [{"data": {"id": 99}}]}}
    mock_k_http = MagicMock()
    mock_k_http.get = AsyncMock(return_value=k_resp)
    mock_k_http.is_closed = False
    k_client._http_client = mock_k_http
    k_client.get_by_id = AsyncMock(  # type: ignore[method-assign]
        return_value=_make_product(StoreType.KOSIK, "99", "Košík Máslo")
    )

    k1 = await k_client.search("máslo", limit=5)
    k2 = await k_client.search("máslo", limit=5)
    assert len(k1) == 1
    assert len(k2) == 1
    assert mock_k_http.get.await_count == 1
