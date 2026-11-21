import asyncio
import logging
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional
import yaml

from app.clients.base import BaseStoreClient
from app.core.config import settings
from app.models.enums import PriceAdvantage, StoreType
from app.models.product import StoreProduct
from app.models.comparison import (
    BasketComparisonItem,
    BasketComparisonResponse,
    ComparisonResponse,
    MatchedProductPair,
)
from app.models.staples import StapleDefinition, StaplesCatalog
from app.services.bilingual import BilingualQueryService
from app.services.matcher import ProductMatchingService
from app.services.ollama import OllamaService
from app.services.voice_formatter import VoiceResponseFormatter

logger = logging.getLogger(__name__)


class PriceComparisonService:
    """Core domain service orchestrating price comparisons between stores."""

    def __init__(
        self,
        rohlik_client: BaseStoreClient,
        kosik_client: BaseStoreClient,
        bilingual_service: Optional[BilingualQueryService] = None,
        matching_service: Optional[ProductMatchingService] = None,
        voice_formatter: Optional[VoiceResponseFormatter] = None,
        ollama_service: Optional[OllamaService] = None,
        staples_path: Optional[Path] = None,
    ) -> None:
        self.rohlik = rohlik_client
        self.kosik = kosik_client
        self.bilingual = bilingual_service or BilingualQueryService()
        self.matcher = matching_service or ProductMatchingService(
            min_similarity_threshold=settings.min_match_similarity_score
        )
        self.formatter = voice_formatter or VoiceResponseFormatter()
        self.ollama = ollama_service or OllamaService()
        self.staples_path = staples_path or settings.staples_config_path
        self._staples: Dict[str, StapleDefinition] = {}
        self._load_staples()

    def _load_staples(self) -> None:
        """Load staple item catalog from YAML."""
        if not self.staples_path.exists():
            logger.warning(f"Staples file not found at {self.staples_path}")
            return

        try:
            with open(self.staples_path, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)
            catalog = StaplesCatalog.model_validate(raw_data)
            for item in catalog.staples:
                self._staples[item.id] = item
                for kw in item.keywords:
                    self._staples[kw.lower()] = item
        except Exception as exc:
            logger.error(f"Failed to load staples catalog: {exc}")

    def get_all_staples(self) -> List[StapleDefinition]:
        """Return unique configured staple items."""
        seen = set()
        unique: List[StapleDefinition] = []
        for s in self._staples.values():
            if s.id not in seen:
                seen.add(s.id)
                unique.append(s)
        return unique

    async def compare_single_item(self, query: str) -> ComparisonResponse:
        """Compare a single grocery item between Rohlik and Kosik."""
        clean_query = query.strip()
        staple = self._staples.get(clean_query.lower())
        category: Optional[str] = None
        labels_by_language: Dict[str, List[str]] = {}
        translations: Dict[str, str] = {}
        source_language: Optional[str] = None

        if staple:
            rohlik_term = staple.rohlik_query
            kosik_term = staple.kosik_query
            translated_term = staple.name_cs
            category = staple.category
            translations = {"en": staple.name_en, "cs": staple.name_cs}
            labels_by_language = staple.labels or {"en": staple.keywords}
            source_language = "en"
        else:
            t_res = await self.bilingual.translate_query_async(
                clean_query, ollama_service=self.ollama
            )
            translated_term = t_res.primary_term
            rohlik_term = translated_term
            kosik_term = translated_term
            category = t_res.category
            translations = t_res.translations
            labels_by_language = t_res.labels
            source_language = t_res.source_language

        flat_labels = labels_by_language.get(
            settings.default_language,
            labels_by_language.get("en", labels_by_language.get("cs", [])),
        )

        # Fetch more candidates so we can rank by unit price
        rohlik_task = self.rohlik.search(rohlik_term, limit=10)
        kosik_task = self.kosik.search(kosik_term, limit=10)

        r_products, k_products = await asyncio.gather(
            rohlik_task, kosik_task, return_exceptions=True
        )

        r_list: List[StoreProduct] = r_products if isinstance(r_products, list) else []
        k_list: List[StoreProduct] = k_products if isinstance(k_products, list) else []

        best_pair = self.matcher.find_best_pair(clean_query, translated_term, r_list, k_list)

        # Filter relevant products for clean ranked list display
        r_filtered = self.matcher._filter_relevant_products(translated_term, r_list, clean_query)
        k_filtered = self.matcher._filter_relevant_products(translated_term, k_list, clean_query)

        # If filtering emptied both lists, fall back to raw lists
        if not r_filtered and not k_filtered:
            r_filtered = r_list
            k_filtered = k_list

        # Build ranked lists (by unit price ascending) for UI display
        rohlik_ranked = self.matcher.rank_by_unit_price(r_filtered)
        kosik_ranked = self.matcher.rank_by_unit_price(k_filtered)

        if not best_pair:
            voice_summaries = self.formatter.format_by_language(None, translations, clean_query)
            return ComparisonResponse(
                query=clean_query,
                query_translated=translated_term,
                advantage=PriceAdvantage.UNAVAILABLE,
                cheapest_store=None,
                price_difference=Decimal("0.00"),
                percentage_savings=Decimal("0.0"),
                voice_summary_en=voice_summaries["en"],
                voice_summary_cs=voice_summaries["cs"],
                primary_pair=None,
                all_pairs=[],
                rohlik_candidates=r_list,
                kosik_candidates=k_list,
                rohlik_ranked=rohlik_ranked,
                kosik_ranked=kosik_ranked,
                category=category,
                labels=flat_labels,
                source_language=source_language,
                translations=translations,
                labels_by_language=labels_by_language,
                voice_summaries=voice_summaries,
            )

        voice_summaries = self.formatter.format_by_language(best_pair, translations, clean_query)

        return ComparisonResponse(
            query=clean_query,
            query_translated=translated_term,
            advantage=best_pair.advantage,
            cheapest_store=best_pair.cheaper_store,
            price_difference=best_pair.price_difference,
            percentage_savings=best_pair.percentage_savings,
            voice_summary_en=voice_summaries["en"],
            voice_summary_cs=voice_summaries["cs"],
            primary_pair=best_pair,
            all_pairs=[best_pair],
            rohlik_candidates=r_list,
            kosik_candidates=k_list,
            rohlik_ranked=rohlik_ranked,
            kosik_ranked=kosik_ranked,
            category=category,
            labels=flat_labels,
            source_language=source_language,
            translations=translations,
            labels_by_language=labels_by_language,
            voice_summaries=voice_summaries,
        )

    async def compare_basket(self, items: List[BasketComparisonItem]) -> BasketComparisonResponse:
        """Compare a multi-item grocery basket across both stores."""
        pairs: List[MatchedProductPair] = []
        total_rohlik = Decimal("0.00")
        total_kosik = Decimal("0.00")

        # Compare items concurrently
        tasks = [self.compare_single_item(item.query) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for item, res in zip(items, results):
            if isinstance(res, ComparisonResponse) and res.primary_pair:
                pair = res.primary_pair
                pairs.append(pair)
                qty = Decimal(item.quantity)
                if pair.rohlik_product:
                    total_rohlik += pair.rohlik_product.price * qty
                if pair.kosik_product:
                    total_kosik += pair.kosik_product.price * qty

        if total_rohlik == total_kosik:
            advantage = PriceAdvantage.TIED
            cheapest_store = None
            diff = Decimal("0.00")
            pct = Decimal("0.0")
            summary = f"Both stores have identical basket total: {total_rohlik:.2f} CZK."
        elif total_rohlik < total_kosik:
            advantage = PriceAdvantage.ROHLIK_CHEAPER
            cheapest_store = StoreType.ROHLIK
            diff = total_kosik - total_rohlik
            pct = Decimal(round((diff / total_kosik) * 100, 1)) if total_kosik > 0 else Decimal("0.0")
            summary = (
                f"Rohlik is cheaper for your basket at {total_rohlik:.2f} CZK "
                f"compared to {total_kosik:.2f} CZK on Kosik, saving you {diff:.2f} CZK ({pct}%)."
            )
        else:
            advantage = PriceAdvantage.KOSIK_CHEAPER
            cheapest_store = StoreType.KOSIK
            diff = total_rohlik - total_kosik
            pct = Decimal(round((diff / total_rohlik) * 100, 1)) if total_rohlik > 0 else Decimal("0.0")
            summary = (
                f"Kosik is cheaper for your basket at {total_kosik:.2f} CZK "
                f"compared to {total_rohlik:.2f} CZK on Rohlik, saving you {diff:.2f} CZK ({pct}%)."
            )

        return BasketComparisonResponse(
            total_rohlik=total_rohlik,
            total_kosik=total_kosik,
            advantage=advantage,
            cheapest_store=cheapest_store,
            savings=diff,
            percentage_savings=pct,
            voice_summary_en=summary,
            items=pairs,
        )
