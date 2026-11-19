from difflib import SequenceMatcher
from decimal import Decimal
import re
from typing import List, Optional, Tuple
from app.models.enums import PriceAdvantage, StoreType
from app.models.product import StoreProduct
from app.models.comparison import MatchedProductPair


class ProductMatchingService:
    """Matches corresponding products from Rohlik and Kosik and calculates price advantage."""

    def __init__(self, min_similarity_threshold: float = 0.40) -> None:
        self.min_similarity_threshold = min_similarity_threshold

    def find_best_pair(
        self,
        query: str,
        query_cs: str,
        rohlik_candidates: List[StoreProduct],
        kosik_candidates: List[StoreProduct],
    ) -> Optional[MatchedProductPair]:
        """Find the most relevant matching pair of products between both stores."""
        if not rohlik_candidates and not kosik_candidates:
            return None

        # If only one store has products
        if not rohlik_candidates and kosik_candidates:
            kosik_best = kosik_candidates[0]
            return MatchedProductPair(
                query=query,
                query_cs=query_cs,
                rohlik_product=None,
                kosik_product=kosik_best,
                advantage=PriceAdvantage.KOSIK_CHEAPER,
                cheaper_store=StoreType.KOSIK,
                price_difference=Decimal("0.00"),
                percentage_savings=Decimal("0.0"),
                match_confidence=1.0,
            )

        if rohlik_candidates and not kosik_candidates:
            rohlik_best = rohlik_candidates[0]
            return MatchedProductPair(
                query=query,
                query_cs=query_cs,
                rohlik_product=rohlik_best,
                kosik_product=None,
                advantage=PriceAdvantage.ROHLIK_CHEAPER,
                cheaper_store=StoreType.ROHLIK,
                price_difference=Decimal("0.00"),
                percentage_savings=Decimal("0.0"),
                match_confidence=1.0,
            )

        # Both stores returned candidates: find highest scoring match
        best_score = -1.0
        best_r: Optional[StoreProduct] = None
        best_k: Optional[StoreProduct] = None

        for r_prod in rohlik_candidates:
            for k_prod in kosik_candidates:
                score = self.compute_similarity(r_prod.name, k_prod.name)
                # Boost if brand matches
                if r_prod.brand and k_prod.brand and r_prod.brand.lower() == k_prod.brand.lower():
                    score = min(1.0, score + 0.25)

                if score > best_score:
                    best_score = score
                    best_r = r_prod
                    best_k = k_prod

        # If best pair is below threshold, check if candidates match the query itself
        if best_score < self.min_similarity_threshold:
            query_keywords = [w for w in re.sub(r"[^\w\s]", "", query_cs.lower()).split() if len(w) > 2]

            r_matches = [
                p for p in rohlik_candidates
                if any(kw in p.name.lower() for kw in query_keywords)
            ]
            k_matches = [
                p for p in kosik_candidates
                if any(kw in p.name.lower() for kw in query_keywords)
            ]

            if r_matches and not k_matches:
                # Only Rohlik truly has the requested item
                return MatchedProductPair(
                    query=query,
                    query_cs=query_cs,
                    rohlik_product=r_matches[0],
                    kosik_product=None,
                    advantage=PriceAdvantage.ROHLIK_CHEAPER,
                    cheaper_store=StoreType.ROHLIK,
                    price_difference=Decimal("0.00"),
                    percentage_savings=Decimal("0.0"),
                    match_confidence=1.0,
                )
            elif k_matches and not r_matches:
                # Only Kosik truly has the requested item
                return MatchedProductPair(
                    query=query,
                    query_cs=query_cs,
                    rohlik_product=None,
                    kosik_product=k_matches[0],
                    advantage=PriceAdvantage.KOSIK_CHEAPER,
                    cheaper_store=StoreType.KOSIK,
                    price_difference=Decimal("0.00"),
                    percentage_savings=Decimal("0.0"),
                    match_confidence=1.0,
                )
            elif r_matches and k_matches:
                # Both have items matching the query keywords, pair top matches
                best_r = r_matches[0]
                best_k = k_matches[0]
                best_score = max(0.5, self.compute_similarity(best_r.name, best_k.name))
            else:
                # Neither candidate title contains the query keywords
                best_r = rohlik_candidates[0]
                best_k = kosik_candidates[0]
                best_score = self.compute_similarity(best_r.name, best_k.name)

        if best_r is None or best_k is None:
            return None

        return self.compare_products(query, query_cs, best_r, best_k, best_score)

    def compare_products(
        self,
        query: str,
        query_cs: str,
        rohlik_prod: StoreProduct,
        kosik_prod: StoreProduct,
        confidence: float = 1.0,
    ) -> MatchedProductPair:
        """Compute price advantage, delta, and percentage savings between two products."""
        r_price = rohlik_prod.price
        k_price = kosik_prod.price

        # Check for tie
        if r_price == k_price:
            return MatchedProductPair(
                query=query,
                query_cs=query_cs,
                rohlik_product=rohlik_prod,
                kosik_product=kosik_prod,
                advantage=PriceAdvantage.TIED,
                cheaper_store=None,
                price_difference=Decimal("0.00"),
                percentage_savings=Decimal("0.0"),
                match_confidence=confidence,
            )

        if r_price < k_price:
            diff = k_price - r_price
            savings_pct = Decimal(round((diff / k_price) * 100, 1))
            return MatchedProductPair(
                query=query,
                query_cs=query_cs,
                rohlik_product=rohlik_prod,
                kosik_product=kosik_prod,
                advantage=PriceAdvantage.ROHLIK_CHEAPER,
                cheaper_store=StoreType.ROHLIK,
                price_difference=diff,
                percentage_savings=savings_pct,
                match_confidence=confidence,
            )
        else:
            diff = r_price - k_price
            savings_pct = Decimal(round((diff / r_price) * 100, 1))
            return MatchedProductPair(
                query=query,
                query_cs=query_cs,
                rohlik_product=rohlik_prod,
                kosik_product=kosik_prod,
                advantage=PriceAdvantage.KOSIK_CHEAPER,
                cheaper_store=StoreType.KOSIK,
                price_difference=diff,
                percentage_savings=savings_pct,
                match_confidence=confidence,
            )

    @staticmethod
    def compute_similarity(title_a: str, title_b: str) -> float:
        """Token-based and sequence matching score between two product names."""
        norm_a = re.sub(r"[^\w\s]", "", title_a.lower())
        norm_b = re.sub(r"[^\w\s]", "", title_b.lower())

        tokens_a = set(norm_a.split())
        tokens_b = set(norm_b.split())

        if not tokens_a or not tokens_b:
            return 0.0

        jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
        seq_ratio = SequenceMatcher(None, norm_a, norm_b).ratio()

        # Weighted combination of token overlap and character sequence
        return round(0.6 * jaccard + 0.4 * seq_ratio, 3)
