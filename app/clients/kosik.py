import asyncio
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import quote
import httpx
from app.clients.base import BaseStoreClient
from app.core.config import settings
from app.models.enums import StoreType, UnitType
from app.models.product import StoreProduct

logger = logging.getLogger(__name__)


class KosikStoreClient(BaseStoreClient):
    """Client for Košík.cz using Constructor search + front product detail API."""

    CONSTRUCTOR_KEY = "key_KaoSi20AnZwxsIZ5"

    def __init__(
        self,
        user_token: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self.user_token = user_token or settings.kosik_user_token
        self.timeout = timeout
        self.base_url = "https://www.kosik.cz"
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def store_type(self) -> StoreType:
        return StoreType.KOSIK

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
                "Referer": "https://www.kosik.cz/",
            }
            if self.user_token:
                headers["Authorization"] = f"Bearer {self.user_token}"

            self._http_client = httpx.AsyncClient(
                headers=headers,
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._http_client

    async def search(self, query: str, limit: int = 5) -> List[StoreProduct]:
        """Search products on Kosik using Constructor.io + product details."""
        client = await self._get_client()
        encoded_query = quote(query.strip())
        search_url = (
            f"https://ac.cnstrc.com/search/{encoded_query}"
            f"?key={self.CONSTRUCTOR_KEY}&num_results_per_page={limit}"
        )

        try:
            resp = await client.get(search_url)
            if resp.status_code != 200:
                logger.warning(f"Kosik search returned status {resp.status_code} for '{query}'")
                return []

            results = resp.json().get("response", {}).get("results", [])
            product_items: List[Dict[str, Any]] = []
            for item in results:
                data = item.get("data", {})
                pid = data.get("id")
                if pid:
                    product_items.append({
                        "id": str(pid),
                        "fallback_title": item.get("value"),
                        "image_url": data.get("image_url"),
                        "url": data.get("url"),
                    })

            if not product_items:
                return []

            fetch_tasks = [self.get_by_id(item["id"]) for item in product_items[:limit]]
            detailed_products = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            products: List[StoreProduct] = []
            for prod in detailed_products:
                if isinstance(prod, StoreProduct) and prod:
                    products.append(prod)

            return products

        except Exception as exc:
            logger.warning(f"Error during Kosik search for '{query}': {exc}")
            return []

    async def get_by_id(self, product_id: str) -> Optional[StoreProduct]:
        """Fetch details of a single product on Kosik by ID."""
        client = await self._get_client()
        url = f"https://www.kosik.cz/api/front/product/{product_id}"

        try:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                raw_prod = data.get("product", {})
                if raw_prod:
                    return self._parse_product(raw_prod)
        except Exception as exc:
            logger.debug(f"Error fetching Kosik product {product_id}: {exc}")

        return None

    async def health_check(self) -> bool:
        """Verify Kosik reachability."""
        try:
            client = await self._get_client()
            search_url = f"https://ac.cnstrc.com/search/test?key={self.CONSTRUCTOR_KEY}&num_results_per_page=1"
            resp = await client.get(search_url)
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        """Close connection pool."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    def _parse_product(self, item: Dict[str, Any]) -> Optional[StoreProduct]:
        """Convert Kosik JSON item into normalized StoreProduct."""
        product_id = str(item.get("id") or item.get("productId") or "")
        name = item.get("name") or item.get("cleanName")
        if not product_id or not name:
            return None

        # Brand parsing (can be dict with 'name' or string)
        brand_raw = item.get("brand")
        if isinstance(brand_raw, dict):
            brand = brand_raw.get("name")
        elif brand_raw:
            brand = str(brand_raw)
        else:
            brand = None

        # Price parsing
        price_raw = item.get("price")
        if isinstance(price_raw, dict):
            price_val = price_raw.get("price") or price_raw.get("amount") or 0.0
        else:
            price_val = price_raw or 0.0
        price = Decimal(str(price_val))

        # Sale & original recommended price
        is_on_sale = bool(item.get("isSale"))
        rec_obj = item.get("recommendedPrice") or item.get("recommendedSellPrice")
        if isinstance(rec_obj, dict):
            rec_val = rec_obj.get("price") or rec_obj.get("amount")
        else:
            rec_val = rec_obj
        original_price = (
            Decimal(str(rec_val))
            if (rec_val is not None and float(rec_val) > float(price))
            else None
        )

        # Unit mapping & price per unit
        unit_raw = str(item.get("unit") or "").lower()
        unit_type = self._normalize_unit(unit_raw)

        unit_price_obj = item.get("pricePerUnit")
        unit_price_val = None
        if isinstance(unit_price_obj, dict):
            unit_price_val = unit_price_obj.get("price") or unit_price_obj.get("amount")
            unit_name = unit_price_obj.get("unit")
            if unit_name:
                unit_type = self._normalize_unit(str(unit_name))
        elif unit_price_obj is not None:
            unit_price_val = unit_price_obj

        unit_price = (
            Decimal(str(round(float(unit_price_val), 2)))
            if unit_price_val is not None
            else None
        )

        # Links and media
        url_path = item.get("url") or ""
        full_url = f"https://www.kosik.cz{url_path}" if url_path.startswith("/") else f"https://www.kosik.cz/{url_path}"

        img_raw = item.get("image") or item.get("imageUrl")
        if isinstance(img_raw, dict):
            img_raw = img_raw.get("url") or img_raw.get("main")
        if img_raw and isinstance(img_raw, str):
            image_url = img_raw.replace("WIDTHxHEIGHT", "200x200")
        else:
            image_url = None

        return StoreProduct(
            store=StoreType.KOSIK,
            product_id=product_id,
            name=name.strip(),
            brand=brand,
            price=price,
            original_price=original_price,
            is_on_sale=is_on_sale,
            unit_type=unit_type,
            unit_price=unit_price,
            package_amount=None,
            in_stock=bool(item.get("plannedStock", True) or not item.get("availability") == "sold_out"),
            url=full_url,
            image_url=image_url,
        )

    def _normalize_unit(self, unit_str: str) -> UnitType:
        """Map raw text unit to UnitType enum."""
        unit_str = unit_str.strip().lower()
        if "kg" in unit_str or "kilo" in unit_str:
            return UnitType.KILOGRAM
        if "ml" in unit_str:
            return UnitType.MILLILITER
        if "g" in unit_str or "gram" in unit_str:
            return UnitType.GRAM
        if "l" in unit_str or "litr" in unit_str:
            return UnitType.LITER
        if "ks" in unit_str or "kus" in unit_str or "pc" in unit_str:
            return UnitType.PIECE
        return UnitType.UNKNOWN
