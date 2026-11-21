from difflib import SequenceMatcher
from decimal import Decimal
import re
import unicodedata
from typing import List, Optional, Set
from app.models.enums import PriceAdvantage, StoreType
from app.models.product import StoreProduct
from app.models.comparison import MatchedProductPair


class ProductMatchingService:
    """Matches corresponding products from Rohlik and Kosik, ranking by normalized unit price."""

    KNOWN_BRANDS: Set[str] = {
        "madeta", "milko", "olma", "kunin", "pilsner", "urquell", "barilla",
        "miil", "tatra", "bohemilk", "delacto", "parmareggio", "elle & vire",
        "dr. halíř", "dr halir", "podestýlková", "schubert", "president",
    }

    # Irrelevant item keywords to exclude when searching for pure staples
    EXCLUSIONS = {
        "máslo": ["croissant", "těsto", "zelenina", "sušenky", "brioška", "pomazánka s máslem", "příchutí"],
        "mléko": ["čokoláda", "sušenky", "káva s mlékem", "koktejl"],
        "vejce": ["těstoviny", "salát s vejci", "pomazánka"],
        "pivo": ["sklenice", "otvírák", "tričko"],
        "banán": ["bread", "chléb", "pečivo", "sirup", "kaše", "křupky", "želé", "ice", "sušenky", "tyčinka", "snack", "cocofir", "protein"],
    }

    STOP_TOKENS: Set[str] = {
        "1", "2", "3", "4", "5", "6", "8", "10", "12", "ks", "kus", "kusů", "balení",
        "g", "kg", "kilo", "l", "litr", "ml", "pcs", "bio", "1kg", "250g", "05l", "1l",
    }

    def __init__(self, min_similarity_threshold: float = 0.40) -> None:
        self.min_similarity_threshold = min_similarity_threshold

    @staticmethod
    def _strip_accents(text: str) -> str:
        """Remove diacritics for insensitive matching."""
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(c for c in nfkd if not unicodedata.combining(c))

    def _extract_stems(self, query: str, query_cs: str) -> Set[str]:
        """Extract core search stems from query strings, ignoring units and quantities."""
        combined = f"{query} {query_cs}".lower()
        words = re.findall(r"[a-zA-Zá-žÁ-Ž]+", combined)
        meaningful = [w for w in words if len(w) > 2 and w not in self.STOP_TOKENS]
        stems = set()
        for m in meaningful:
            norm = self._strip_accents(m)
            # Use root of at least 3 characters
            root_len = max(3, len(norm) - 1) if len(norm) > 4 else len(norm)
            stems.add(norm[:root_len])
        return stems

    def find_best_pair(
        self,
        query: str,
        query_cs: str,
        rohlik_candidates: List[StoreProduct],
        kosik_candidates: List[StoreProduct],
    ) -> Optional[MatchedProductPair]:
        """Find the best pair of products, ranking by normalized unit price or matching brand."""
        if not rohlik_candidates and not kosik_candidates:
            return None

        # Clean irrelevant peripheral items
        r_filtered = self._filter_relevant_products(query_cs, rohlik_candidates, query)
        k_filtered = self._filter_relevant_products(query_cs, kosik_candidates, query)

        # If both became empty due to over-aggressive filtering, fall back to candidates
        if not r_filtered and not k_filtered:
            r_filtered = rohlik_candidates
            k_filtered = kosik_candidates

        # If only one store has products
        if not r_filtered and k_filtered:
            k_best = self._get_best_unit_price(k_filtered)
            return MatchedProductPair(
                query=query,
                query_cs=query_cs,
                rohlik_product=None,
                kosik_product=k_best,
                advantage=PriceAdvantage.KOSIK_CHEAPER,
                cheaper_store=StoreType.KOSIK,
                price_difference=Decimal("0.00"),
                percentage_savings=Decimal("0.0"),
                match_confidence=1.0,
            )

        if r_filtered and not k_filtered:
            r_best = self._get_best_unit_price(r_filtered)
            return MatchedProductPair(
                query=query,
                query_cs=query_cs,
                rohlik_product=r_best,
                kosik_product=None,
                advantage=PriceAdvantage.ROHLIK_CHEAPER,
                cheaper_store=StoreType.ROHLIK,
                price_difference=Decimal("0.00"),
                percentage_savings=Decimal("0.0"),
                match_confidence=1.0,
            )

        # Check if the query specifically mentions a brand
        is_brand_search = any(b in query.lower() or b in query_cs.lower() for b in self.KNOWN_BRANDS)

        if is_brand_search:
            # Pair matching brand
            best_pair = self._find_brand_match(query, query_cs, r_filtered, k_filtered)
            if best_pair:
                return best_pair

        # Default for generic staples: Pick the best value deal (lowest unit price) from each store
        r_best = self._get_best_unit_price(r_filtered)
        k_best = self._get_best_unit_price(k_filtered)

        confidence = self.compute_similarity(r_best.name, k_best.name)
        return self.compare_products(query, query_cs, r_best, k_best, confidence)

    def compare_products(
        self,
        query: str,
        query_cs: str,
        rohlik_prod: StoreProduct,
        kosik_prod: StoreProduct,
        confidence: float = 1.0,
    ) -> MatchedProductPair:
        """Compare two products prioritizing normalized unit price (per kg/l), fallback to pack price."""
        # Ensure confidence is always strictly within [0.0, 1.0]
        clamped_confidence = min(1.0, max(0.0, float(confidence)))

        # Use unit price (per kg/l) if both have it and share same unit type
        if rohlik_prod.unit_price and kosik_prod.unit_price and rohlik_prod.unit_type == kosik_prod.unit_type:
            r_comp = rohlik_prod.unit_price
            k_comp = kosik_prod.unit_price
            using_unit_price = True
        else:
            r_comp = rohlik_prod.price
            k_comp = kosik_prod.price
            using_unit_price = False

        if r_comp == k_comp:
            return MatchedProductPair(
                query=query,
                query_cs=query_cs,
                rohlik_product=rohlik_prod,
                kosik_product=kosik_prod,
                advantage=PriceAdvantage.TIED,
                cheaper_store=None,
                price_difference=Decimal("0.00"),
                percentage_savings=Decimal("0.0"),
                match_confidence=clamped_confidence,
            )

        if r_comp < k_comp:
            diff = (k_comp - r_comp) if using_unit_price else (kosik_prod.price - rohlik_prod.price)
            savings_pct = Decimal(round((diff / k_comp) * 100, 1))
            return MatchedProductPair(
                query=query,
                query_cs=query_cs,
                rohlik_product=rohlik_prod,
                kosik_product=kosik_prod,
                advantage=PriceAdvantage.ROHLIK_CHEAPER,
                cheaper_store=StoreType.ROHLIK,
                price_difference=diff,
                percentage_savings=savings_pct,
                match_confidence=clamped_confidence,
            )
        else:
            diff = (r_comp - k_comp) if using_unit_price else (rohlik_prod.price - kosik_prod.price)
            savings_pct = Decimal(round((diff / r_comp) * 100, 1))
            return MatchedProductPair(
                query=query,
                query_cs=query_cs,
                rohlik_product=rohlik_prod,
                kosik_product=kosik_prod,
                advantage=PriceAdvantage.KOSIK_CHEAPER,
                cheaper_store=StoreType.KOSIK,
                price_difference=diff,
                percentage_savings=savings_pct,
                match_confidence=clamped_confidence,
            )

    def _filter_relevant_products(
        self,
        query_cs: str,
        products: List[StoreProduct],
        query: Optional[str] = None,
    ) -> List[StoreProduct]:
        """Exclude peripheral products (e.g. croissants when searching butter) and irrelevant results."""
        clean_q = query_cs.lower()
        exclusion_list: List[str] = []
        for key, words in self.EXCLUSIONS.items():
            if key in clean_q or (query and key in query.lower()):
                exclusion_list.extend(words)

        stems = self._extract_stems(query or "", query_cs)

        filtered: List[StoreProduct] = []
        for p in products:
            p_name_lower = p.name.lower()
            p_name_norm = self._strip_accents(p_name_lower)
            p_brand_norm = self._strip_accents(p.brand.lower()) if p.brand else ""

            # Check exclusions
            if any(excl in p_name_lower for excl in exclusion_list):
                continue

            # If stems exist, product must contain at least one stem in its name or brand
            if stems:
                matches_stem = any(s in p_name_norm or (p_brand_norm and s in p_brand_norm) for s in stems)
                if not matches_stem:
                    continue

            filtered.append(p)

        return filtered

    def _get_best_unit_price(self, products: List[StoreProduct]) -> StoreProduct:
        """Find product with the lowest normalized unit price (per kg/l), fallback to lowest price."""
        return self.rank_by_unit_price(products)[0]

    def rank_by_unit_price(self, products: List[StoreProduct]) -> List[StoreProduct]:
        """Return products sorted ascending by unit price (per kg/l), fallback to pack price."""
        def sort_key(p: StoreProduct) -> Decimal:
            if p.unit_price and p.unit_price > 0:
                return p.unit_price
            return p.price

        return sorted(products, key=sort_key)

    def _find_brand_match(
        self,
        query: str,
        query_cs: str,
        r_list: List[StoreProduct],
        k_list: List[StoreProduct],
    ) -> Optional[MatchedProductPair]:
        """Find identical brand and title match."""
        best_score = -1.0
        best_r: Optional[StoreProduct] = None
        best_k: Optional[StoreProduct] = None

        for r in r_list:
            for k in k_list:
                score = self.compute_similarity(r.name, k.name)
                if r.brand and k.brand and r.brand.lower() == k.brand.lower():
                    score += 0.3
                if score > best_score:
                    best_score = score
                    best_r = r
                    best_k = k

        if best_r and best_k and best_score >= self.min_similarity_threshold:
            clamped_score = min(1.0, max(0.0, float(best_score)))
            return self.compare_products(query, query_cs, best_r, best_k, clamped_score)
        return None

    @classmethod
    def compute_similarity(cls, title_a: str, title_b: str) -> float:
        """Compute token and sequence similarity between two product names, discounting units/numbers."""
        norm_a = cls._strip_accents(re.sub(r"[^\w\s]", "", title_a.lower()))
        norm_b = cls._strip_accents(re.sub(r"[^\w\s]", "", title_b.lower()))

        raw_tokens_a = set(norm_a.split())
        raw_tokens_b = set(norm_b.split())

        # Filter out standalone numbers, measurement units, and stop words
        tokens_a = {t for t in raw_tokens_a if t not in cls.STOP_TOKENS and not t.isdigit()}
        tokens_b = {t for t in raw_tokens_b if t not in cls.STOP_TOKENS and not t.isdigit()}

        # Fallback to raw tokens if all tokens were filtered
        effective_a = tokens_a or raw_tokens_a
        effective_b = tokens_b or raw_tokens_b

        if not effective_a or not effective_b:
            return 0.0

        jaccard = len(effective_a & effective_b) / len(effective_a | effective_b)
        seq_ratio = SequenceMatcher(None, norm_a, norm_b).ratio()

        score = round(0.6 * jaccard + 0.4 * seq_ratio, 3)
        return min(1.0, max(0.0, score))
