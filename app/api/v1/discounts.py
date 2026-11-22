import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import get_comparison_service, get_price_history_service
from app.models.enums import StoreType, UnitType
from app.models.product import ProductSale, StoreProduct
from app.services.comparator import PriceComparisonService
from app.services.price_history import PriceHistoryService

router = APIRouter()


class DiscountedProductItem(BaseModel):
    """A discounted store product with its active sales and expiration metadata."""

    query: str = Field(..., description="Watchlist item or search query that matched this product")
    category: Optional[str] = Field(default=None, description="Tracked grocery category if applicable")
    product: StoreProduct = Field(..., description="Normalized product with current effective price")
    best_sale: Optional[ProductSale] = Field(default=None, description="Highest-discount active sale matching filters")
    all_sales: List[ProductSale] = Field(default_factory=list, description="All active discounts on this product")


class DiscountTrackerResponse(BaseModel):
    """Response payload for the live Discount Tracker."""

    scanned_queries: int = Field(..., ge=0)
    total_discounts: int = Field(..., ge=0)
    fetched_at: str = Field(..., description="UTC ISO timestamp of scan")
    cached: bool = Field(default=False, description="Whether results were served from persisted daily scan")
    items: List[DiscountedProductItem] = Field(default_factory=list)


def _pick_best_sale(
    product: StoreProduct,
    include_expiration: bool,
) -> tuple[Optional[ProductSale], List[ProductSale]]:
    """Return (best_sale, filtered_sales) for a product respecting include_expiration."""
    filtered = [
        s
        for s in product.sales
        if include_expiration or s.sale_type.lower() != "expiration"
    ]
    if not filtered and product.is_on_sale:
        filtered = [
            ProductSale(
                sale_type=product.sale_type or "sale",
                price=product.price,
                original_price=product.original_price,
                unit_price=product.unit_price,
                discount_percentage=product.discount_percentage,
                ends_at=product.sale_ends_at,
            )
        ]
    if not filtered:
        return None, []
    best = max(
        filtered,
        key=lambda s: (s.discount_percentage or 0, -float(s.price)),
    )
    return best, filtered


@router.get("", response_model=DiscountTrackerResponse)
async def get_active_discounts(
    q: Optional[str] = Query(default=None, description="Optional search query to scan live discounts for"),
    store: Optional[StoreType] = Query(default=None, description="Optional store filter ('rohlik' or 'kosik')"),
    include_expiration: bool = Query(
        default=True,
        description="Include near-expiration clearance discounts",
    ),
    limit_items: int = Query(
        default=25,
        ge=1,
        le=50,
        description="Maximum number of watchlist items to scan when no query is given",
    ),
    refresh: bool = Query(
        default=False,
        description="Force a live scan instead of returning the persisted daily discount snapshot",
    ),
    comparator: PriceComparisonService = Depends(get_comparison_service),
    history: PriceHistoryService = Depends(get_price_history_service),
) -> DiscountTrackerResponse:
    """Return active discounts from the persisted daily scan or run a live store scan."""
    if not (q and q.strip()) and not refresh:
        scanned_at, cached_rows = history.get_latest_discount_snapshots(
            store=store.value if store else None
        )
        if scanned_at is not None and cached_rows:
            cached_items: List[DiscountedProductItem] = []
            for r in cached_rows:
                sales_objs = [ProductSale(**s) for s in r.get("sales", [])]
                try:
                    ut = UnitType(r["unit_type"])
                except ValueError:
                    ut = UnitType.UNKNOWN
                prod = StoreProduct(
                    store=StoreType(r["store"]),
                    product_id=r["product_id"],
                    name=r["product_name"],
                    brand=r.get("brand"),
                    price=Decimal(str(r["price"])),
                    original_price=(
                        Decimal(str(r["original_price"]))
                        if r.get("original_price") is not None
                        else None
                    ),
                    is_on_sale=True,
                    discount_percentage=r.get("discount_percentage"),
                    sale_type=r.get("sale_type"),
                    sale_ends_at=r.get("sale_ends_at"),
                    sales=sales_objs,
                    unit_type=ut,
                    unit_price=(
                        Decimal(str(r["unit_price"]))
                        if r.get("unit_price") is not None
                        else None
                    ),
                    url=r.get("url"),
                    image_url=r.get("image_url"),
                )
                best_sale, filtered_sales = _pick_best_sale(prod, include_expiration=include_expiration)
                if not best_sale:
                    continue
                cached_items.append(
                    DiscountedProductItem(
                        query=r["item_query"],
                        category=r.get("category"),
                        product=prod,
                        best_sale=best_sale,
                        all_sales=filtered_sales,
                    )
                )
            cached_items.sort(
                key=lambda item: (
                    -(item.best_sale.discount_percentage or 0 if item.best_sale else 0),
                    item.best_sale.ends_at or "9999-12-31" if item.best_sale else "9999-12-31",
                    float(item.product.price),
                )
            )
            return DiscountTrackerResponse(
                scanned_queries=len({r["item_query"] for r in cached_rows}),
                total_discounts=len(cached_items),
                fetched_at=scanned_at.isoformat(),
                cached=True,
                items=cached_items,
            )

    targets: List[Tuple[str, str, Optional[str]]] = []
    if q and q.strip():
        clean_q = q.strip()
        translation = await comparator.bilingual.translate_query_async(
            clean_q,
            ollama_service=comparator.ollama,
        )
        targets.append((clean_q, translation.primary_term or clean_q, None))
    else:
        tracked = history.list_tracked_items(active_only=True)[:limit_items]
        for item in tracked:
            targets.append((item.query, item.query_cs or item.query, item.category))

    sem = asyncio.Semaphore(6)
    per_query_limit = 10 if q else 6

    async def _scan_one(
        label: str,
        search_term: str,
        category: Optional[str],
    ) -> List[tuple[str, Optional[str], StoreProduct]]:
        async with sem:
            tasks = []
            want_r = store in (None, StoreType.ROHLIK)
            want_k = store in (None, StoreType.KOSIK)
            if want_r:
                tasks.append(comparator.rohlik.search(search_term, limit=per_query_limit))
            if want_k:
                tasks.append(comparator.kosik.search(search_term, limit=per_query_limit))
            results = await asyncio.gather(*tasks, return_exceptions=True)

            raw_products: List[StoreProduct] = []
            for res in results:
                if isinstance(res, list):
                    raw_products.extend(res)

            if q:
                raw_products = comparator.matcher._filter_relevant_products(
                    search_term,
                    raw_products,
                    label,
                )
            return [(label, category, p) for p in raw_products]

    scanned = await asyncio.gather(
        *[_scan_one(label, term, cat) for label, term, cat in targets]
    )

    seen_keys: set[tuple[StoreType, str]] = set()
    discounted_items: List[DiscountedProductItem] = []
    to_persist: List[Tuple[str, Optional[str], StoreProduct]] = []

    for group in scanned:
        for label, category, product in group:
            key = (product.store, product.product_id)
            if key in seen_keys:
                continue
            if product.sales or product.is_on_sale:
                to_persist.append((label, category, product))
            best_sale, filtered_sales = _pick_best_sale(product, include_expiration=include_expiration)
            if not best_sale:
                continue
            seen_keys.add(key)
            discounted_items.append(
                DiscountedProductItem(
                    query=label,
                    category=category,
                    product=product,
                    best_sale=best_sale,
                    all_sales=filtered_sales,
                )
            )

    now_dt = datetime.now(timezone.utc)
    if not (q and q.strip()) and store is None and to_persist:
        history.save_discount_snapshots(to_persist, scanned_at=now_dt)

    discounted_items.sort(
        key=lambda item: (
            -(item.best_sale.discount_percentage or 0 if item.best_sale else 0),
            item.best_sale.ends_at or "9999-12-31" if item.best_sale else "9999-12-31",
            float(item.product.price),
        )
    )

    return DiscountTrackerResponse(
        scanned_queries=len(targets),
        total_discounts=len(discounted_items),
        fetched_at=now_dt.isoformat(),
        cached=False,
        items=discounted_items,
    )
