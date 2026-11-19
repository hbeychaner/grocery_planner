import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional
import httpx
from app.clients.base import BaseStoreClient
from app.core.config import settings
from app.models.enums import StoreType, UnitType
from app.models.product import StoreProduct

logger = logging.getLogger(__name__)


class KosikStoreClient(BaseStoreClient):
    """Client for Košík.cz online supermarket."""

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
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._http_client

    async def search(self, query: str, limit: int = 5) -> List[StoreProduct]:
        """Search products on Kosik using public front catalog endpoint."""
        client = await self._get_client()
        # Kosik search uses slug or search query
        slug_encoded = query.strip().replace(" ", "-").lower()
        endpoints = [
            (f"/api/front/page/search?slug={slug_encoded}&limit={limit}", "get"),
            ("/api/front/products", "get_params"),
        ]

        raw_products: List[Dict[str, Any]] = []

        for endpoint, method_type in endpoints:
            try:
                if method_type == "get":
                    response = await client.get(endpoint)
                else:
                    response = await client.get(endpoint, params={"search": query, "limit": limit})

                if response.status_code == 200:
                    data = response.json()
                    # Kosik payload can be structured in page.products or items or products
                    if isinstance(data, dict):
                        page_data = data.get("page", {})
                        if isinstance(page_data, dict):
                            raw_products = page_data.get("products", {}).get("items", [])
                        if not raw_products:
                            raw_products = data.get("products", {}).get("items", [])
                        if not raw_products:
                            raw_products = data.get("items", []) or data.get("data", [])

                    if raw_products:
                        break
            except Exception as exc:
                logger.debug(f"Kosik search endpoint '{endpoint}' error: {exc}")
                continue

        products: List[StoreProduct] = []
        for item in raw_products[:limit]:
            try:
                product = self._parse_product(item)
                if product:
                    products.append(product)
            except Exception as exc:
                logger.debug(f"Failed to parse Kosik item: {exc}")
                continue

        return products

    async def get_by_id(self, product_id: str) -> Optional[StoreProduct]:
        """Fetch details of a single product on Kosik."""
        client = await self._get_client()
        try:
            response = await client.get(f"/api/front/product/{product_id}")
            if response.status_code == 200:
                data = response.json()
                item = data.get("product") or data.get("data") or data
                return self._parse_product(item)
        except Exception as exc:
            logger.warning(f"Error fetching Kosik product {product_id}: {exc}")
        return None

    async def health_check(self) -> bool:
        """Verify Kosik accessibility."""
        try:
            client = await self._get_client()
            resp = await client.get("/api/front/page/search?slug=test&limit=1")
            return resp.status_code in (200, 404)
        except Exception:
            return False

    async def close(self) -> None:
        """Close connection pool."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    def _parse_product(self, item: Dict[str, Any]) -> Optional[StoreProduct]:
        """Convert Kosik JSON item into normalized StoreProduct."""
        product_id = str(item.get("id") or item.get("productId") or "")
        name = item.get("name") or item.get("title")
        if not product_id or not name:
            return None

        # Price parsing
        price_val = item.get("price")
        if isinstance(price_val, dict):
            price_raw = price_val.get("amount") or price_val.get("full") or 0.0
        else:
            price_raw = price_val or 0.0
        price = Decimal(str(price_raw))

        # Original / sale price
        orig_price_val = item.get("originalPrice") or item.get("oldPrice")
        if isinstance(orig_price_val, dict):
            orig_raw = orig_price_val.get("amount") or orig_price_val.get("full")
        else:
            orig_raw = orig_price_val
        original_price = Decimal(str(orig_raw)) if orig_raw else None
        is_on_sale = bool(original_price and original_price > price)

        # Unit mapping
        unit_raw = str(item.get("unit") or item.get("unitName") or "").lower()
        unit_type = self._normalize_unit(unit_raw)

        # Unit price
        unit_price_raw = item.get("unitPrice") or item.get("pricePerUnit")
        unit_price = Decimal(str(unit_price_raw)) if unit_price_raw else None

        # Package quantity
        package_amount_raw = item.get("packageAmount") or item.get("weight") or item.get("volume")
        package_amount = Decimal(str(package_amount_raw)) if package_amount_raw else None

        # Links and media
        url_path = item.get("url") or item.get("slug") or product_id
        full_url = f"https://www.kosik.cz/{url_path.lstrip('/')}"
        image_url = item.get("image") or item.get("imageUrl") or item.get("mainImage")

        return StoreProduct(
            store=StoreType.KOSIK,
            product_id=product_id,
            name=name.strip(),
            brand=item.get("brand"),
            price=price,
            original_price=original_price,
            is_on_sale=is_on_sale,
            unit_type=unit_type,
            unit_price=unit_price,
            package_amount=package_amount,
            in_stock=item.get("inStock", True),
            url=full_url,
            image_url=image_url,
        )

    def _normalize_unit(self, unit_str: str) -> UnitType:
        """Map raw text unit to UnitType enum."""
        unit_str = unit_str.strip().lower()
        if "kg" in unit_str or "kilo" in unit_str:
            return UnitType.KILOGRAM
        if "g" in unit_str or "gram" in unit_str:
            return UnitType.GRAM
        if "l" in unit_str or "litr" in unit_str:
            return UnitType.LITER
        if "ml" in unit_str:
            return UnitType.MILLILITER
        if "ks" in unit_str or "kus" in unit_str or "pc" in unit_str:
            return UnitType.PIECE
        return UnitType.UNKNOWN
