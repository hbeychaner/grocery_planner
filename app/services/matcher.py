import logging
import os
import re
import unicodedata
from decimal import Decimal
from typing import Any, List, Optional, Set, Tuple

import spacy
from spacy.lang.cs.stop_words import STOP_WORDS as CS_STOP_WORDS
from spacy.lang.en.stop_words import STOP_WORDS as EN_STOP_WORDS

try:
    from sentence_transformers import SentenceTransformer, util
    _HAS_TRANSFORMERS = True
except ImportError:
    _HAS_TRANSFORMERS = False

from app.core.config import settings
from app.models.enums import PriceAdvantage, StoreType, UnitType
from app.models.product import StoreProduct
from app.models.comparison import MatchedProductPair
from app.services.embeddings import pairwise_cosine_similarity

logger = logging.getLogger(__name__)

# Standard measurement units to exclude from lemma comparisons
MEASUREMENT_UNITS: Set[str] = {
    "kg", "g", "gram", "kilo", "l", "litr", "ml", "ks", "kus", "kusů", "pcs",
    "balení", "bal", "pack", "cl", "dl",
}


class ProductMatchingService:
    """Matches and ranks products across supermarkets using spaCy NLP and multilingual embeddings.
    
    Replaces brittle heuristic keyword and brand lists with:
      - spaCy tokenization, normalization, and language-specific stop word removal.
      - Dictionary lookup and pipeline lemmatization (Czech and English).
      - Multilingual sentence transformer dense embeddings for cross-lingual semantic similarity.
    """

    _nlp_cs: Optional[Any] = None
    _nlp_en: Optional[Any] = None
    _embedding_model: Optional[Any] = None

    def __init__(self, min_similarity_threshold: float = 0.55) -> None:
        self.min_similarity_threshold = min_similarity_threshold
        self._init_nlp()

    @classmethod
    def _init_nlp(cls) -> None:
        """Initialize spaCy pipelines and multilingual embedding model once."""
        if cls._nlp_cs is None:
            try:
                cls._nlp_cs = spacy.blank("cs")
                cls._nlp_cs.add_pipe("lemmatizer", config={"mode": "lookup"})
                cls._nlp_cs.initialize()
            except Exception as e:
                logger.warning(f"Could not initialize Czech spaCy lemmatizer: {e}")
                cls._nlp_cs = spacy.blank("cs")

        if cls._nlp_en is None:
            try:
                cls._nlp_en = spacy.load("en_core_web_sm")
            except Exception:
                cls._nlp_en = spacy.blank("en")

        if cls._embedding_model is None and _HAS_TRANSFORMERS and settings.embedding_provider.strip().lower() == "local":
            try:
                # Use cached local weights to operate seamlessly offline
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
                cls._embedding_model = SentenceTransformer(
                    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                    local_files_only=True,
                )
            except Exception as e:
                logger.debug(f"SentenceTransformer offline load fallback: {e}")
                cls._embedding_model = None

    @classmethod
    def get_lemmas(cls, text: str, lang: str = "cs") -> Set[str]:
        """Extract normalized lemmas from text using spaCy, stripping stop words and units."""
        cls._init_nlp()
        nlp = cls._nlp_cs if lang == "cs" else cls._nlp_en
        stops = CS_STOP_WORDS if lang == "cs" else EN_STOP_WORDS

        doc = nlp(text.lower())
        lemmas: Set[str] = set()
        for token in doc:
            if token.is_punct or token.like_num or token.is_space:
                continue
            lemma = token.lemma_.strip().lower() if token.lemma_ else token.text.strip().lower()
            if lemma and lemma not in stops and lemma not in MEASUREMENT_UNITS and len(lemma) > 1:
                lemmas.add(lemma)
                norm_lemma = cls._strip_accents(lemma)
                if norm_lemma != lemma:
                    lemmas.add(norm_lemma)
        return lemmas

    @staticmethod
    def _strip_accents(text: str) -> str:
        """Remove diacritics for insensitive matching."""
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(c for c in nfkd if not unicodedata.combining(c))

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

        # Filter relevant products using spaCy lemmatization and semantic similarity
        r_filtered = self._filter_relevant_products(query_cs, rohlik_candidates, query)
        k_filtered = self._filter_relevant_products(query_cs, kosik_candidates, query)

        # Fallback to candidates if filtering emptied both lists
        if not r_filtered and not k_filtered:
            r_filtered = rohlik_candidates
            k_filtered = kosik_candidates

        # If only one store has relevant products
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

        # Pick the best value deal (lowest unit price) from each store so primary_pair
        # always matches the #1 Best Value item shown at index 0 of each ranked list.
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
        # Ensure confidence is strictly within [0.0, 1.0]
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
        """Filter products by NLP relevance to query using lemmatization and multilingual semantic scoring."""
        if not products:
            return []

        q_cs_lemmas = self.get_lemmas(query_cs, "cs")
        q_lemmas = set(q_cs_lemmas)
        if query:
            q_lemmas |= self.get_lemmas(query, "en")

        # Detect whether candidates include items whose brand does NOT collide with the query
        # (e.g. fresh "Avokádo Hass" has brand=None, whereas spice brand "Avokádo Medová hořčice" has brand="Avokádo").
        has_non_brand_matches = any(
            not (p.brand and (self.get_lemmas(p.brand, "cs") & q_lemmas))
            for p in products
        )

        full_cs_matches: List[StoreProduct] = []
        partial_matches: List[StoreProduct] = []

        for p in products:
            eval_name = p.name
            brand_collides = False
            if has_non_brand_matches and p.brand:
                brand_lemmas = self.get_lemmas(p.brand, "cs")
                if brand_lemmas & q_lemmas:
                    brand_collides = True
                    stripped = re.sub(re.escape(p.brand), "", p.name, flags=re.IGNORECASE).strip()
                    if stripped:
                        eval_name = stripped

            p_lemmas = self.get_lemmas(eval_name, "cs")
            if p.brand and not brand_collides:
                p_lemmas |= self.get_lemmas(p.brand, "cs")

            # Prefer candidates that satisfy ALL Czech query lemmas (e.g. both "jablečný" AND "ocet")
            if q_cs_lemmas and q_cs_lemmas <= p_lemmas:
                full_cs_matches.append(p)
                continue

            # Check 1: Partial lemma overlap with search query
            if bool(q_lemmas & p_lemmas):
                partial_matches.append(p)
                continue

            # If the query collided with the brand name and the remaining product title
            # has zero lemma overlap with the query, do not rescue via loose embedding similarity.
            if brand_collides:
                continue

            # Check 2: Semantic embedding similarity if available (Gemini or local)
            target_query = query_cs or query or ""
            sem_sim = pairwise_cosine_similarity(target_query, eval_name)
            if sem_sim is not None and sem_sim >= 0.50:
                partial_matches.append(p)
                continue

        # When multi-word Czech query has exact full-lemma matches (e.g. "jablečný" + "ocet"),
        # drop partial matches (e.g. plain "ocet kvasný lihový" or "džus jablečný").
        filtered = full_cs_matches if full_cs_matches else partial_matches
        filtered = self._filter_dominant_unit_type(filtered)
        filtered = self._filter_by_organic_preference(filtered, query_cs, query)
        return self._filter_by_frozen_preference(filtered, query_cs, query)

    @classmethod
    def is_organic(cls, text: str) -> bool:
        """Return True when product title or query explicitly indicates BIO / organic."""
        if not text:
            return False
        norm = cls._strip_accents(text.lower())
        return bool(re.search(r"\b(bio|organic|eko)\b", norm))

    @classmethod
    def is_frozen(cls, text: str) -> bool:
        """Return True when product title or query explicitly indicates frozen food."""
        if not text:
            return False
        norm = cls._strip_accents(text.lower())
        return bool(re.search(r"\b(mrazen[aey]?|zmrazen[aey]?|hluboce\s+zmrazen[aey]?|frozen|protlak)\b", norm))

    @classmethod
    def _filter_by_frozen_preference(
        cls, products: List[StoreProduct], query_cs: str, query: str
    ) -> List[StoreProduct]:
        """Separate frozen products from fresh products unless the query asks for frozen."""
        if len(products) <= 1:
            return products

        wants_frozen = cls.is_frozen(query_cs) or cls.is_frozen(query)
        if wants_frozen:
            frozen_only = [p for p in products if cls.is_frozen(p.name)]
            return frozen_only if frozen_only else products

        fresh_only = [p for p in products if not cls.is_frozen(p.name)]
        return fresh_only if fresh_only else products

    @classmethod
    def _filter_by_organic_preference(
        cls, products: List[StoreProduct], query_cs: str, query: str
    ) -> List[StoreProduct]:
        """Separate BIO/organic products from regular products unless the query asks for BIO."""
        if len(products) <= 1:
            return products

        wants_bio = cls.is_organic(query_cs) or cls.is_organic(query)
        if wants_bio:
            bio_only = [p for p in products if cls.is_organic(p.name)]
            return bio_only if bio_only else products

        regular_only = [p for p in products if not cls.is_organic(p.name)]
        return regular_only if regular_only else products

    @staticmethod
    def _filter_dominant_unit_type(products: List[StoreProduct]) -> List[StoreProduct]:
        """Keep candidates matching the dominant physical unit_type (e.g. exclude tablet 'pcs' from liquid 'l')."""
        if len(products) <= 1:
            return products

        from collections import Counter

        counts = Counter(
            p.unit_type for p in products if p.unit_type and p.unit_type != UnitType.UNKNOWN
        )
        if len(counts) <= 1:
            return products

        dominant_unit, dominant_count = counts.most_common(1)[0]
        # Only filter when there is a strict majority / plurality winner
        top_two = counts.most_common(2)
        if len(top_two) == 2 and top_two[0][1] == top_two[1][1]:
            return products

        return [
            p for p in products
            if p.unit_type == dominant_unit or p.unit_type == UnitType.UNKNOWN
        ]

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
        """Find matching brand or identical product packaging across stores using semantic scoring."""
        best_score = -1.0
        best_r: Optional[StoreProduct] = None
        best_k: Optional[StoreProduct] = None

        for r in r_list:
            for k in k_list:
                score = self.compute_similarity(r.name, k.name)
                # Boost if both explicitly declare identical non-empty brand
                if r.brand and k.brand and r.brand.strip().lower() == k.brand.strip().lower():
                    score = min(1.0, score + 0.20)
                if score > best_score:
                    best_score = score
                    best_r = r
                    best_k = k

        # Strong semantic threshold for declaring an exact brand/item pair
        if best_r and best_k and best_score >= max(0.65, self.min_similarity_threshold):
            return self.compare_products(query, query_cs, best_r, best_k, best_score)
        return None

    @classmethod
    def compute_similarity(cls, title_a: str, title_b: str) -> float:
        """Compute semantic and lexical similarity between two product titles."""
        cls._init_nlp()
        lemmas_a = cls.get_lemmas(title_a)
        lemmas_b = cls.get_lemmas(title_b)

        # Jaccard overlap on lemmatized content tokens (discounting stop words and units)
        if lemmas_a and lemmas_b:
            jaccard = len(lemmas_a & lemmas_b) / len(lemmas_a | lemmas_b)
        else:
            jaccard = 0.0

        # Semantic embedding cosine similarity using configured provider (Gemini or local)
        sem_sim = pairwise_cosine_similarity(title_a, title_b)
        if sem_sim is not None:
            # Combined metric: 60% multilingual semantic embedding + 40% lemmatized token overlap
            score = 0.6 * sem_sim + 0.4 * jaccard
        else:
            # Fallback to lemmatized token Jaccard + sequence matcher ratio
            from difflib import SequenceMatcher
            norm_a = cls._strip_accents(title_a.lower())
            norm_b = cls._strip_accents(title_b.lower())
            seq_ratio = SequenceMatcher(None, norm_a, norm_b).ratio()
            score = 0.6 * jaccard + 0.4 * seq_ratio

        return round(min(1.0, max(0.0, float(score))), 3)
