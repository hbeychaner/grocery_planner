import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional
import httpx
from app.clients.base import BaseStoreClient, normalize_piece_unit_price
from app.core.config import settings
from app.models.enums import StoreType, UnitType
from app.models.product import StoreProduct

logger = logging.getLogger(__name__)


class RohlikStoreClient(BaseStoreClient):
    """Client for Rohlík.cz grocery service using verified live search-metadata endpoint."""

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self.username = username or settings.rohlik_username
        self.password = password or settings.rohlik_password
        self.timeout = timeout
        self.base_url = "https://www.rohlik.cz"
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def store_type(self) -> StoreType:
        return StoreType.ROHLIK

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
                "Referer": "https://www.rohlik.cz/",
            }
            self._http_client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._http_client

    async def search(self, query: str, limit: int = 5) -> List[StoreProduct]:
        """Search products on Rohlik."""
        client = await self._get_client()
        url = "/services/frontend-service/search-metadata"
        params = {
            "search": query,
            "offset": 0,
            "limit": limit,
            "companyId": 1,
        }

        try:
            response = await client.get(url, params=params)
            if response.status_code != 200:
                logger.warning(
                    f"Rohlik search returned status {response.status_code} for query '{query}'"
                )
                return []

            data = response.json()
            raw_products = data.get("data", {}).get("productList", [])

            products: List[StoreProduct] = []
            for item in raw_products[:limit]:
                try:
                    product = self._parse_product(item)
                    if product:
                        products.append(product)
                except Exception as exc:
                    logger.debug(f"Failed to parse Rohlik item: {exc}")
                    continue

            return products

        except httpx.RequestError as exc:
            logger.warning(f"Network error querying Rohlik for '{query}': {exc}")
            return []

    async def get_by_id(self, product_id: str) -> Optional[StoreProduct]:
        """Fetch a single product by ID."""
        client = await self._get_client()
        url = f"/services/frontend-service/product/{product_id}"

        try:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json().get("data", {})
                return self._parse_product(data)
        except Exception as exc:
            logger.warning(f"Error fetching Rohlik product {product_id}: {exc}")

        return None

    async def health_check(self) -> bool:
        """Check if Rohlik endpoint responds."""
        try:
            client = await self._get_client()
            resp = await client.get("/services/frontend-service/search-metadata?search=test&limit=1&companyId=1")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    def _parse_product(self, item: Dict[str, Any]) -> Optional[StoreProduct]:
        """Transform Rohlik JSON item into StoreProduct model."""
        product_id = str(item.get("productId") or item.get("id") or "")
        name = item.get("productName") or item.get("name") or item.get("title")
        if not product_id or not name:
            return None

        # Price parsing
        price_obj = item.get("price") or {}
        if isinstance(price_obj, dict):
            current_price_raw = price_obj.get("full") or price_obj.get("amount") or 0.0
        else:
            current_price_raw = price_obj or 0.0

        price = Decimal(str(current_price_raw))

        # Sale / regular price
        orig_obj = item.get("originalPrice")
        orig_raw = orig_obj.get("full") if isinstance(orig_obj, dict) else orig_obj
        original_price = Decimal(str(orig_raw)) if (orig_raw and float(orig_raw) > float(price)) else None
        is_on_sale = bool(original_price and original_price > price)

        # Unit type & textual amount
        textual_amount = item.get("textualAmount") or ""
        unit_raw = (item.get("unit") or textual_amount or "").lower()
        unit_type = self._normalize_unit(unit_raw)

        # Unit price
        unit_price_obj = item.get("pricePerUnit")
        unit_price_raw = unit_price_obj.get("full") if isinstance(unit_price_obj, dict) else unit_price_obj
        unit_price = Decimal(str(unit_price_raw)) if unit_price_raw else None

        unit_type, unit_price = normalize_piece_unit_price(
            name=name,
            textual_amount=textual_amount,
            price=price,
            unit_type=unit_type,
            unit_price=unit_price,
        )

        # Direct link
        link_path = item.get("link") or ""
        url = f"https://www.rohlik.cz{link_path}" if link_path.startswith("/") else f"https://www.rohlik.cz/{link_path}"

        # Image
        img_path = item.get("imgPath") or ""
        if img_path.startswith("http"):
            image_url = img_path
        elif img_path:
            image_url = f"https://cdn.rohlik.cz{img_path}"
        else:
            image_url = None

        return StoreProduct(
            store=StoreType.ROHLIK,
            product_id=product_id,
            name=name.strip(),
            brand=item.get("brand"),
            price=price,
            original_price=original_price,
            is_on_sale=is_on_sale,
            unit_type=unit_type,
            unit_price=unit_price,
            package_amount=None,
            in_stock=item.get("inStock", True),
            url=url,
            image_url=image_url,
        )

    def _normalize_unit(self, unit_str: str) -> UnitType:
        """Map text unit string to standardized UnitType enum."""
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
