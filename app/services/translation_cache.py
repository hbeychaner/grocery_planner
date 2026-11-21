import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)


class CachedTranslation(BaseModel):
    """Cached translation record stored in the local SQLite database."""

    normalized_term: str
    source_lang: str
    target_lang: str
    translated_term: str
    category: Optional[str] = None
    labels: Dict[str, List[str]] = Field(default_factory=dict)
    synonyms: Dict[str, List[str]] = Field(default_factory=dict)
    is_compound: bool = False
    source: str = "ollama"
    hit_count: int = 1


class CompoundQueryAnalysis(BaseModel):
    """Result of analyzing whether multi-word queries form a single keyword or separable terms."""

    original_query: str
    is_single_keyword: bool
    is_compound: bool
    sub_queries: List[str] = Field(default_factory=list)
    head_noun: Optional[str] = None
    modifiers: List[str] = Field(default_factory=list)
    reason: str = ""


class TranslationCacheService:
    """Local SQLite cache for translated grocery terms and compound keyword metadata."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path if db_path is not None else settings.translation_db_path
        self._memory_conn: Optional[sqlite3.Connection] = None

        if str(self.db_path) != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)

        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        conn = sqlite3.connect(str(self.db_path))
        return conn

    def _init_schema(self) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS translations (
                    normalized_term TEXT NOT NULL,
                    source_lang TEXT NOT NULL,
                    target_lang TEXT NOT NULL,
                    translated_term TEXT NOT NULL,
                    category TEXT,
                    labels_json TEXT NOT NULL DEFAULT '{}',
                    synonyms_json TEXT NOT NULL DEFAULT '{}',
                    is_compound INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'ollama',
                    hit_count INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (normalized_term, source_lang, target_lang)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_translations_lookup
                ON translations (normalized_term, target_lang)
                """
            )
            conn.commit()
        finally:
            if self._memory_conn is None:
                conn.close()

    @staticmethod
    def normalize_term(term: str) -> str:
        """Normalize whitespace and casing for consistent SQLite lookups."""
        return re.sub(r"\s+", " ", term.strip().lower())

    def get(
        self,
        term: str,
        target_lang: str = "cs",
        source_lang: Optional[str] = None,
    ) -> Optional[CachedTranslation]:
        """Look up a cached translation and increment hit_count on hit."""
        norm = self.normalize_term(term)
        if not norm:
            return None

        conn = self._get_connection()
        try:
            if source_lang:
                row = conn.execute(
                    """
                    SELECT normalized_term, source_lang, target_lang, translated_term,
                           category, labels_json, synonyms_json, is_compound, source, hit_count
                    FROM translations
                    WHERE normalized_term = ? AND source_lang = ? AND target_lang = ?
                    """,
                    (norm, source_lang, target_lang),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT normalized_term, source_lang, target_lang, translated_term,
                           category, labels_json, synonyms_json, is_compound, source, hit_count
                    FROM translations
                    WHERE normalized_term = ? AND target_lang = ?
                    ORDER BY hit_count DESC
                    LIMIT 1
                    """,
                    (norm, target_lang),
                ).fetchone()

            if not row:
                return None

            conn.execute(
                """
                UPDATE translations
                SET hit_count = hit_count + 1, updated_at = CURRENT_TIMESTAMP
                WHERE normalized_term = ? AND source_lang = ? AND target_lang = ?
                """,
                (row[0], row[1], row[2]),
            )
            conn.commit()

            return CachedTranslation(
                normalized_term=row[0],
                source_lang=row[1],
                target_lang=row[2],
                translated_term=row[3],
                category=row[4],
                labels=json.loads(row[5] or "{}"),
                synonyms=json.loads(row[6] or "{}"),
                is_compound=bool(row[7]),
                source=row[8],
                hit_count=int(row[9]) + 1,
            )
        finally:
            if self._memory_conn is None:
                conn.close()

    def upsert(self, record: CachedTranslation) -> None:
        """Insert or update a translation record in SQLite."""
        norm = self.normalize_term(record.normalized_term)
        if not norm:
            return

        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO translations (
                    normalized_term, source_lang, target_lang, translated_term,
                    category, labels_json, synonyms_json, is_compound, source, hit_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(normalized_term, source_lang, target_lang) DO UPDATE SET
                    translated_term = excluded.translated_term,
                    category = COALESCE(excluded.category, translations.category),
                    labels_json = excluded.labels_json,
                    synonyms_json = excluded.synonyms_json,
                    is_compound = excluded.is_compound,
                    source = excluded.source,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    norm,
                    record.source_lang,
                    record.target_lang,
                    record.translated_term,
                    record.category,
                    json.dumps(record.labels, ensure_ascii=False),
                    json.dumps(record.synonyms, ensure_ascii=False),
                    1 if record.is_compound else 0,
                    record.source,
                    record.hit_count,
                ),
            )
            conn.commit()
        finally:
            if self._memory_conn is None:
                conn.close()

    def seed_from_dictionary(self, dictionary: Dict[str, List[str]]) -> None:
        """Seed SQLite cache idempotently from built-in bilingual dictionary."""
        conn = self._get_connection()
        try:
            rows = []
            for en_term, cs_variants in dictionary.items():
                norm = self.normalize_term(en_term)
                if not norm or not cs_variants:
                    continue
                is_compound = 1 if " " in norm else 0
                synonyms = {"cs": cs_variants[1:]} if len(cs_variants) > 1 else {}
                labels = {"en": [en_term], "cs": [cs_variants[0]]}
                rows.append(
                    (
                        norm,
                        "en",
                        "cs",
                        cs_variants[0],
                        None,
                        json.dumps(labels, ensure_ascii=False),
                        json.dumps(synonyms, ensure_ascii=False),
                        is_compound,
                        "dictionary",
                        1,
                    )
                )

            conn.executemany(
                """
                INSERT OR IGNORE INTO translations (
                    normalized_term, source_lang, target_lang, translated_term,
                    category, labels_json, synonyms_json, is_compound, source, hit_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            if self._memory_conn is None:
                conn.close()

    def count(self) -> int:
        """Return total number of cached translation entries."""
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT COUNT(*) FROM translations").fetchone()
            return int(row[0]) if row else 0
        finally:
            if self._memory_conn is None:
                conn.close()

    def close(self) -> None:
        """Close persistent in-memory connection if open."""
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None


class CompoundKeywordAnalyzer:
    """Determines whether multi-word grocery queries represent a single compound keyword or separable terms."""

    def __init__(self, cache: Optional[TranslationCacheService] = None) -> None:
        self.cache = cache
        self._nlp_en: Any = None
        self._nlp_loaded = False

    def _get_nlp_en(self) -> Any:
        if not self._nlp_loaded:
            self._nlp_loaded = True
            try:
                import spacy

                self._nlp_en = spacy.load("en_core_web_sm")
            except Exception as exc:
                logger.warning(f"spaCy en_core_web_sm unavailable for compound analysis: {exc}")
                self._nlp_en = None
        return self._nlp_en

    def analyze(self, query: str, target_lang: str = "cs") -> CompoundQueryAnalysis:
        """Determine whether tokens form one compound keyword, modified phrase, or separate items."""
        cleaned = re.sub(r"\s+", " ", query.strip())
        words = cleaned.split()
        if len(words) <= 1:
            return CompoundQueryAnalysis(
                original_query=cleaned,
                is_single_keyword=True,
                is_compound=False,
                sub_queries=[cleaned] if cleaned else [],
                head_noun=cleaned.lower() if cleaned else None,
                reason="single_token",
            )

        # 1. Exact cache hit: known compound or pre-translated multi-word keyword
        if self.cache is not None:
            cached = self.cache.get(cleaned, target_lang=target_lang)
            if cached is not None:
                return CompoundQueryAnalysis(
                    original_query=cleaned,
                    is_single_keyword=True,
                    is_compound=True,
                    sub_queries=[cleaned],
                    head_noun=words[-1].lower(),
                    reason="cached_phrase",
                )

        # 2. Explicit list separators (commas, 'and', '&') -> separable items
        if re.search(r"[,&]|\band\b|\ba\b", cleaned, flags=re.IGNORECASE):
            parts = [
                p.strip()
                for p in re.split(r"\s*[,&]\s*|\s+\band\b\s+", cleaned, flags=re.IGNORECASE)
                if p.strip()
            ]
            if len(parts) > 1:
                return CompoundQueryAnalysis(
                    original_query=cleaned,
                    is_single_keyword=False,
                    is_compound=False,
                    sub_queries=parts,
                    reason="explicit_conjunction_split",
                )

        # 3. Syntactic dependency & noun-chunk analysis via spaCy
        nlp = self._get_nlp_en()
        if nlp is not None:
            doc = nlp(cleaned)
            noun_chunks = list(doc.noun_chunks)

            # Check for non-compositional noun-noun compounds (e.g. "peanut butter", "ice cream")
            has_compound_dep = any(tok.dep_ == "compound" for tok in doc)
            if has_compound_dep and len(noun_chunks) <= 1:
                root_tokens = [tok for tok in doc if tok.dep_ == "ROOT"]
                head = root_tokens[0].text.lower() if root_tokens else words[-1].lower()
                modifiers = [tok.text.lower() for tok in doc if tok.text.lower() != head]
                return CompoundQueryAnalysis(
                    original_query=cleaned,
                    is_single_keyword=True,
                    is_compound=True,
                    sub_queries=[cleaned],
                    head_noun=head,
                    modifiers=modifiers,
                    reason="spacy_compound_dependency",
                )

            # Single noun chunk with adjectival modifier (e.g. "sour cream", "sourdough bread")
            if len(noun_chunks) == 1:
                chunk = noun_chunks[0]
                head = chunk.root.text.lower()
                modifiers = [
                    tok.text.lower()
                    for tok in chunk
                    if tok.i != chunk.root.i and tok.pos_ in ("ADJ", "NOUN", "PROPN")
                ]
                return CompoundQueryAnalysis(
                    original_query=cleaned,
                    is_single_keyword=True,
                    is_compound=True,
                    sub_queries=[cleaned],
                    head_noun=head,
                    modifiers=modifiers,
                    reason="spacy_single_noun_chunk",
                )

            # Multiple disjoint noun chunks without syntactic link (e.g. "milk bread")
            if len(noun_chunks) > 1:
                chunks_text = [c.text.strip() for c in noun_chunks if c.text.strip()]
                if len(chunks_text) > 1:
                    return CompoundQueryAnalysis(
                        original_query=cleaned,
                        is_single_keyword=False,
                        is_compound=False,
                        sub_queries=chunks_text,
                        reason="spacy_multiple_noun_chunks",
                    )

        # Default fallback: treat short 2-3 word query as a single phrase to resolve via LLM/cache
        return CompoundQueryAnalysis(
            original_query=cleaned,
            is_single_keyword=True,
            is_compound=True,
            sub_queries=[cleaned],
            head_noun=words[-1].lower(),
            reason="default_phrase",
        )
