from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from app.clients.kupi import KupiClient
from app.models.enums import UnitType
from app.services.bls_client import BlsPriceIngestionService
from app.services.csu_client import CsuPriceIngestionService
from app.services.price_history import PriceHistoryService


def test_kupi_html_parser() -> None:
    sample_html = """
    <div class="group_discounts">
      <div class="product_name"><a href="/sleva/maslo-jihoceske-madeta"><strong>Máslo Jihočeské Madeta</strong></a></div>
      <div class="discounts_shop_name"><span>BILLA</span></div>
      <div class="discount_price_value">34,90&nbsp;Kč</div>
      <div class="price_per_unit">13,96&nbsp;Kč&nbsp;/&nbsp;100&nbsp;g</div>
      <div class="discounts_shop_name"><span>Lidl</span></div>
      <div class="discount_price_value">32,90&nbsp;Kč</div>
      <div class="price_per_unit">13,16&nbsp;Kč&nbsp;/&nbsp;100&nbsp;g</div>
    </div>
    """
    deals = KupiClient._parse_html(sample_html, limit=5)
    assert len(deals) == 2
    assert deals[0].store == "BILLA"
    assert deals[0].product_name == "Máslo Jihočeské Madeta"
    assert deals[0].price == Decimal("34.90")
    assert deals[0].unit_price == Decimal("139.60")
    assert deals[0].unit_type == UnitType.KILOGRAM
    assert deals[1].store == "Lidl"
    assert deals[1].unit_price == Decimal("131.60")


def test_csu_label_and_month_parsing() -> None:
    name, mult, unit = CsuPriceIngestionService._parse_item_label("Máslo [250 g]")
    assert name == "Máslo"
    assert mult == 4.0
    assert unit == "kg"

    name2, mult2, unit2 = CsuPriceIngestionService._parse_item_label("Vejce slepičí čerstvá [10 ks]")
    assert mult2 == pytest.approx(0.1)
    assert unit2 == "pcs"

    dt = CsuPriceIngestionService._parse_czech_month("říjen 2026")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 10


@pytest.mark.asyncio
async def test_csu_ingest_into_sqlite() -> None:
    history = PriceHistoryService(db_path=Path(":memory:"))
    history.add_tracked_item("butter", query_cs="máslo", category="dairy")
    csu = CsuPriceIngestionService(history=history)

    mock_json_stat = {
        "dimension": {
            "CENREP4": {
                "category": {
                    "index": {"01151001": 0},
                    "label": {"01151001": "Máslo [250 g]"},
                }
            },
            "CasM": {
                "category": {
                    "index": {"2026-09": 0, "2026-10": 1},
                    "label": {"2026-09": "září 2026", "2026-10": "říjen 2026"},
                }
            },
        },
        "value": [55.0, 52.5],
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: mock_json_stat
        mock_get.return_value = mock_resp

        res = await csu.ingest_all()
        assert res.datasets_fetched == 2
        assert res.csu_items_matched == 1
        assert res.snapshots_inserted >= 2

    series = history.get_item_history("butter", days=3650)
    assert len(series.csu_series) >= 2
    assert series.csu_series[0].unit_price == 220.0  # 55.0 * 4
    history.close()


@pytest.mark.asyncio
async def test_bls_ingest_with_historical_fx() -> None:
    history = PriceHistoryService(db_path=Path(":memory:"))
    history.add_tracked_item("whole milk", query_cs="plnotučné mléko", category="dairy")
    bls = BlsPriceIngestionService(history=history)

    mock_fx_json = {
        "rates": {
            "2026-10-01": {"CZK": 22.5},
            "2026-10-15": {"CZK": 22.5},
        }
    }
    mock_bls_json = {
        "status": "REQUEST_SUCCEEDED",
        "Results": {
            "series": [
                {
                    "seriesID": "APU0000709112",
                    "data": [{"year": "2026", "period": "M10", "value": "4.000"}],
                }
            ]
        },
    }

    with patch("httpx.AsyncClient.get") as mock_get, patch("httpx.AsyncClient.post") as mock_post:
        mock_fx_resp = AsyncMock()
        mock_fx_resp.status_code = 200
        mock_fx_resp.json = lambda: mock_fx_json
        mock_get.return_value = mock_fx_resp

        mock_bls_resp = AsyncMock()
        mock_bls_resp.status_code = 200
        mock_bls_resp.json = lambda: mock_bls_json
        mock_post.return_value = mock_bls_resp

        res = await bls.ingest_all()
        assert res.series_fetched == 1
        assert res.fx_months_loaded == 1
        assert res.snapshots_inserted == 1

    series = history.get_item_history("whole milk", days=3650)
    assert len(series.bls_series) == 1
    # $4.00/gal * (1 / 3.78541178) * 22.5 CZK/USD ~= 23.78 CZK/l
    assert series.bls_series[0].unit_price == pytest.approx(23.78, abs=0.05)
    history.close()
