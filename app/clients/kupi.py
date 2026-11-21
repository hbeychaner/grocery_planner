import html as html_lib
import logging
import re
from decimal import Decimal
from typing import List, Optional
import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.models.enums import UnitType

logger = logging.getLogger(__name__)


class KupiDeal(BaseModel):
    """Promotional deal across Czech brick-and-mortar supermarkets from Kupi.cz."""

    store: str
    product_name: str
    price: Decimal
    unit_price: Optional[Decimal] = None
    unit_type: UnitType = UnitType.UNKNOWN
    url: str


class KupiClient:
    """Free client for querying promotional grocery prices across Tesco, Lidl, Penny, Kaufland, Billa, Albert via Kupi.cz."""

    BASE_URL = "https://www.kupi.cz"

    def __init__(self, timeout: Optional[float] = None) -> None:
        self.timeout = timeout or settings.request_timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=self.timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
                },
                follow_redirects=True,
            )
        return self._client

    @staticmethod
    def _parse_decimal(text: str) -> Optional[Decimal]:
        cleaned = html_lib.unescape(text).replace("\xa0", " ").strip()
        m = re.search(r"(\d+(?:[.,]\d+)?)", cleaned)
        if not m:
            return None
        try:
            return Decimal(m.group(1).replace(",", "."))
        except Exception:
            return None

    @classmethod
    def _parse_unit_price(cls, text: str) -> tuple[Optional[Decimal], UnitType]:
        cleaned = html_lib.unescape(text).replace("\xa0", " ").strip().lower()
        val = cls._parse_decimal(cleaned)
        if val is None:
            return None, UnitType.UNKNOWN

        # Normalize e.g. '13,96 Kč / 100 g' -> per kg (*10)
        per_part = cleaned.split("/")[-1].strip() if "/" in cleaned else cleaned
        qty_match = re.search(r"(\d+(?:[.,]\d+)?)", per_part)
        qty = Decimal(qty_match.group(1).replace(",", ".")) if qty_match else Decimal("1")

        if "kg" in per_part:
            return (val / qty if qty > 0 else val).quantize(Decimal("0.01")), UnitType.KILOGRAM
        if "g" in per_part:
            return ((val / qty) * Decimal("1000") if qty > 0 else val).quantize(Decimal("0.01")), UnitType.KILOGRAM
        if "ml" in per_part:
            return ((val / qty) * Decimal("1000") if qty > 0 else val).quantize(Decimal("0.01")), UnitType.LITER
        if "l" in per_part:
            return (val / qty if qty > 0 else val).quantize(Decimal("0.01")), UnitType.LITER
        if "ks" in per_part:
            return (val / qty if qty > 0 else val).quantize(Decimal("0.01")), UnitType.PIECE
        return val, UnitType.UNKNOWN

    async def search_deals(self, query_cs: str, limit: int = 12) -> List[KupiDeal]:
        """Fetch active supermarket promotional deals for a Czech grocery term from Kupi.cz."""
        if not query_cs or not query_cs.strip():
            return []

        try:
            client = await self._get_client()
            resp = await client.get("/hledej", params={"f": query_cs.strip()})
            if resp.status_code != 200:
                return []
            return self._parse_html(resp.text, limit=limit)
        except Exception as exc:
            logger.debug(f"Kupi.cz search failed for '{query_cs}': {exc}")
            return []

    @classmethod
    def _parse_html(cls, html: str, limit: int = 12) -> List[KupiDeal]:
        deals: List[KupiDeal] = []
        blocks = re.split(r"<div[^>]*class=\"[^\"]*group_discounts[^\"]*\"[^>]*>", html)[1:]

        for block in blocks:
            name_m = re.search(r"class=\"product_name[^\"]*\"[^>]*>.*?<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, re.S)
            if not name_m:
                continue
            href = name_m.group(1).strip()
            prod_name = re.sub(r"<[^>]+>|\s+", " ", html_lib.unescape(name_m.group(2))).strip()
            full_url = f"{cls.BASE_URL}{href}" if href.startswith("/") else href

            stores = [
                re.sub(r"<[^>]+>|\s+", " ", html_lib.unescape(s)).strip()
                for s in re.findall(r"class=\"discounts_shop_name[^\"]*\"[^>]*>.*?<span[^>]*>(.*?)</span>", block, re.S)
            ]
            prices = re.findall(r"class=\"discount_price_value[^\"]*\"[^>]*>(.*?)<", block, re.S)
            units = re.findall(r"class=\"price_per_unit[^\"]*\"[^>]*>(.*?)<", block, re.S)

            for idx, store_name in enumerate(stores):
                if idx >= len(prices):
                    break
                price_val = cls._parse_decimal(prices[idx])
                if price_val is None:
                    continue
                unit_val, unit_type = cls._parse_unit_price(units[idx]) if idx < len(units) else (None, UnitType.UNKNOWN)
                deals.append(
                    KupiDeal(
                        store=store_name,
                        product_name=prod_name,
                        price=price_val,
                        unit_price=unit_val,
                        unit_type=unit_type,
                        url=full_url,
                    )
                )
                if len(deals) >= limit:
                    return deals

        return deals

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
