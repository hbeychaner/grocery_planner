import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.translation_cache import (
    CachedTranslation,
    CompoundKeywordAnalyzer,
    TranslationCacheService,
)


class QueryTranslationResult(BaseModel):
    """Structured translation output with strict per-language metadata."""

    primary_term: str
    source_language: str = "en"
    target_language: str = "cs"
    translations: Dict[str, str] = Field(default_factory=dict)
    synonyms: Dict[str, List[str]] = Field(default_factory=dict)
    category: Optional[str] = None
    labels: Dict[str, List[str]] = Field(default_factory=dict)
    from_cache: bool = False
    is_compound: bool = False


class BilingualQueryService:
    """Handles multi-language grocery term translation, compound analysis, and SQLite caching."""

    # Curated dictionary of common groceries (EN -> CS with synonyms)
    DICTIONARY: Dict[str, List[str]] = {
        # Dairy & Eggs
        "milk": ["mléko", "čerstvé mléko", "trvanlivé mléko"],
        "whole milk": ["plnotučné mléko", "mléko plnotučné"],
        "semi-skimmed milk": ["polotučné mléko"],
        "skimmed milk": ["odtučněné mléko"],
        "lactose free milk": ["bezelaktózové mléko", "bez laktózy mléko"],
        "butter": ["máslo", "jihočeské máslo"],
        "peanut butter": ["arašídové máslo"],
        "eggs": ["vejce", "vajíčka", "slepičí vejce"],
        "cheese": ["sýr", "tvrdý sýr"],
        "cheddar": ["čedar", "cheddar"],
        "gouda": ["gouda"],
        "mozzarella": ["mozzarella"],
        "parmesan": ["parmazán", "parmigiano"],
        "cottage cheese": ["cottage", "cottage sýr"],
        "cream": ["smetana"],
        "sour cream": ["zakysaná smetana"],
        "heavy cream": ["smetana ke šlehání"],
        "whipped cream": ["šlehačka"],
        "yogurt": ["jogurt", "bílý jogurt"],
        "greek yogurt": ["řecký jogurt"],
        "ice cream": ["zmrzlina"],
        # Bakery & Grains
        "bread": ["chléb", "chleba", "pečivo"],
        "sourdough bread": ["kváskový chléb"],
        "toast bread": ["toustový chléb", "toastový chléb"],
        "roll": ["rohlík", "houska"],
        "baguette": ["bageta"],
        "croissant": ["croissant"],
        "flour": ["mouka", "hladká mouka"],
        "plain flour": ["hladká mouka"],
        "coarse flour": ["hrubá mouka"],
        "sugar": ["cukr", "cukr krupice"],
        "salt": ["sůl"],
        "rice": ["rýže", "jasmínová rýže"],
        "pasta": ["těstoviny", "špagety"],
        "spaghetti": ["špagety"],
        "oats": ["ovesné vločky", "vločky"],
        # Meat & Fish
        "chicken": ["kuře", "kuřecí maso"],
        "chicken breast": ["kuřecí prsa", "kuřecí prsní řízky"],
        "chicken thighs": ["kuřecí stehna"],
        "beef": ["hovězí maso", "hovězí"],
        "minced meat": ["mleté maso"],
        "pork": ["vepřové maso", "vepřové"],
        "bacon": ["slanina", "anglická slanina"],
        "ham": ["šunka", "vepřová šunka"],
        "salmon": ["losos", "filet z lososa"],
        "tuna": ["tuňák"],
        # Produce: Fruit & Veg
        "banana": ["banány", "banán"],
        "bananas": ["banány"],
        "apple": ["jablka", "jablko"],
        "apples": ["jablka"],
        "orange": ["pomeranče", "pomeranč"],
        "lemon": ["citrony", "citron"],
        "lime": ["limetka"],
        "avocado": ["avokádo"],
        "potato": ["brambory", "brambor"],
        "potatoes": ["brambory"],
        "onion": ["cibule", "žlutá cibule"],
        "garlic": ["česnek"],
        "tomato": ["rajčata", "rajče"],
        "tomatoes": ["rajčata"],
        "cucumber": ["okurka", "hadovka okurka"],
        "carrot": ["mrkev"],
        "lettuce": ["salát", "ledový salát"],
        "pepper": ["paprika"],
        "mushrooms": ["žampiony", "houby"],
        # Beverages & Alcohol
        "water": ["voda", "neperlivá voda"],
        "sparkling water": ["perlivá voda"],
        "still water": ["neperlivá voda"],
        "mineral water": ["minerální voda", "minerálka"],
        "beer": ["pivo", "světlý ležák"],
        "pilsner": ["pilsner urquell", "plzeň"],
        "wine": ["víno", "bílé víno", "červené víno"],
        "coffee": ["káva", "zrnková káva", "mletá káva"],
        "tea": ["čaj", "černý čaj"],
        "juice": ["džus", "pomerančový džus"],
        "coke": ["coca-cola", "kola"],
        # Pantry & Cooking
        "oil": ["olej", "slunečnicový olej", "řepkový olej"],
        "olive oil": ["olivový olej", "extra panenský olivový olej"],
    }

    def __init__(self, cache_service: Optional[TranslationCacheService] = None) -> None:
        self.cache = cache_service or TranslationCacheService()
        self.cache.seed_from_dictionary(self.DICTIONARY)
        self.compound_analyzer = CompoundKeywordAnalyzer(cache=self.cache)

        # Build inverted reverse lookup (Czech -> English)
        self.reverse_dict: Dict[str, str] = {}
        for en_term, cs_variants in self.DICTIONARY.items():
            for cs in cs_variants:
                cs_norm = self._strip_accents(cs.lower())
                self.reverse_dict[cs_norm] = en_term

    def translate_to_czech(self, query: str) -> Tuple[str, List[str]]:
        """Translate input search query to primary Czech search term and alternative synonyms."""
        raw = query.strip().lower()
        cleaned = re.sub(r"[^\w\s-]", "", raw)

        # 1. Direct match in dictionary
        if cleaned in self.DICTIONARY:
            variants = self.DICTIONARY[cleaned]
            return variants[0], variants[1:]

        # 2. Check if words form a compound grocery match (e.g. "fresh whole milk" -> "whole milk")
        for en_key, cs_variants in sorted(self.DICTIONARY.items(), key=lambda x: len(x[0]), reverse=True):
            if en_key in cleaned:
                return cs_variants[0], cs_variants[1:]

        # 3. Check if query is already in Czech
        cleaned_no_accents = self._strip_accents(cleaned)
        if cleaned_no_accents in self.reverse_dict:
            return raw, []

        # 4. Unknown query - pass as-is
        return raw, []

    async def translate_query_async(
        self,
        query: str,
        target_lang: Optional[str] = None,
        ollama_service: Optional[Any] = None,
    ) -> QueryTranslationResult:
        """Translate query using SQLite cache -> compound analysis -> dictionary -> Ollama LLM."""
        target = (target_lang or settings.default_catalog_language).lower()
        raw_clean = re.sub(r"\s+", " ", query.strip())
        norm_key = self.cache.normalize_term(raw_clean)

        # 1. Check local SQLite cache for exact phrase match
        cached = self.cache.get(norm_key, target_lang=target)
        if cached is not None:
            translations = {cached.source_lang: norm_key, target: cached.translated_term}
            return QueryTranslationResult(
                primary_term=cached.translated_term,
                source_language=cached.source_lang,
                target_language=target,
                translations=translations,
                synonyms=cached.synonyms,
                category=cached.category,
                labels=cached.labels,
                from_cache=True,
                is_compound=cached.is_compound,
            )

        # 2. Analyze multi-word structure (single compound keyword vs separable terms)
        compound_info = self.compound_analyzer.analyze(raw_clean, target_lang=target)

        # If query lists separate items (e.g., "milk and bread"), translate each independently
        if not compound_info.is_single_keyword and len(compound_info.sub_queries) > 1:
            resolved_terms: List[str] = []
            merged_labels: Dict[str, List[str]] = {}
            for sub_q in compound_info.sub_queries:
                sub_res = await self.translate_query_async(
                    sub_q, target_lang=target, ollama_service=ollama_service
                )
                resolved_terms.append(sub_res.primary_term)
                for lang_code, tag_list in sub_res.labels.items():
                    merged_labels.setdefault(lang_code, []).extend(tag_list)
            combined_term = " ".join(resolved_terms)
            return QueryTranslationResult(
                primary_term=combined_term,
                source_language="en",
                target_language=target,
                translations={"en": raw_clean, target: combined_term},
                labels=merged_labels,
                is_compound=False,
            )

        # 3. Check if already recognizable Czech
        cleaned_no_accents = self._strip_accents(re.sub(r"[^\w\s-]", "", norm_key))
        if cleaned_no_accents in self.reverse_dict:
            en_equiv = self.reverse_dict[cleaned_no_accents]
            return QueryTranslationResult(
                primary_term=raw_clean.lower(),
                source_language="cs",
                target_language=target,
                translations={"cs": raw_clean.lower(), "en": en_equiv},
                labels={"cs": [raw_clean.lower()], "en": [en_equiv]},
                is_compound=compound_info.is_compound,
            )

        # 4. Query Ollama LLM for unknown single/compound terms and persist to SQLite cache
        if ollama_service is not None and getattr(ollama_service, "enabled", False):
            try:
                analysis = await ollama_service.analyze_query(
                    raw_clean, target_languages=settings.supported_languages
                )
                if analysis and analysis.get_translation(target):
                    translated_term = analysis.get_translation(target) or raw_clean
                    self.cache.upsert(
                        CachedTranslation(
                            normalized_term=norm_key,
                            source_lang=analysis.source_language,
                            target_lang=target,
                            translated_term=translated_term,
                            category=analysis.category,
                            labels=analysis.labels,
                            synonyms=analysis.synonyms,
                            is_compound=analysis.is_compound,
                            source="ollama",
                        )
                    )
                    return QueryTranslationResult(
                        primary_term=translated_term,
                        source_language=analysis.source_language,
                        target_language=target,
                        translations=analysis.translations,
                        synonyms=analysis.synonyms,
                        category=analysis.category,
                        labels=analysis.labels,
                        from_cache=False,
                        is_compound=analysis.is_compound,
                    )
            except Exception:
                pass

        # 5. Offline / fallback: if modified phrase (amod + head_noun), fall back to head noun translation
        term, synonyms_list = self.translate_to_czech(raw_clean)
        if term == norm_key and compound_info.head_noun and not (
            compound_info.reason == "spacy_compound_dependency"
        ):
            head_term, head_syns = self.translate_to_czech(compound_info.head_noun)
            if head_term != compound_info.head_noun:
                term = head_term
                synonyms_list = head_syns

        return QueryTranslationResult(
            primary_term=term,
            source_language="en",
            target_language=target,
            translations={"en": raw_clean, target: term},
            synonyms={target: synonyms_list} if synonyms_list else {},
            is_compound=compound_info.is_compound,
        )

    async def translate_to_czech_async(
        self, query: str, ollama_service: Optional[Any] = None
    ) -> Tuple[str, List[str], Optional[str], List[str]]:
        """Backward-compatible wrapper returning (primary_term, synonyms_cs, category, labels_en)."""
        res = await self.translate_query_async(
            query=query, target_lang="cs", ollama_service=ollama_service
        )
        syns_cs = res.synonyms.get("cs", [])
        labels_en = res.labels.get("en", [])
        return res.primary_term, syns_cs, res.category, labels_en

    @staticmethod
    def _strip_accents(text: str) -> str:
        """Remove diacritics for insensitive matching."""
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(c for c in nfkd if not unicodedata.combining(c))
