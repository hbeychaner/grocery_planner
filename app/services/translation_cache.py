import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, create_engine, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from app.core.config import settings

logger = logging.getLogger(__name__)


class TranslationBase(DeclarativeBase):
    """SQLAlchemy declarative base for translation cache models."""


class TranslationRecord(TranslationBase):
    """ORM model for cached grocery translations."""

    __tablename__ = "translations"
    __table_args__ = (
        Index("idx_translations_lookup", "normalized_term", "target_lang"),
    )

    normalized_term: Mapped[str] = mapped_column(String, primary_key=True)
    source_lang: Mapped[str] = mapped_column(String, primary_key=True)
    target_lang: Mapped[str] = mapped_column(String, primary_key=True)
    translated_term: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    labels_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    synonyms_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_compound: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String, nullable=False, default="ollama")
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


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
    """SQLAlchemy-backed SQLite cache for translated grocery terms and compound metadata."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path if db_path is not None else settings.translation_db_path

        if str(self.db_path) == ":memory:":
            self.engine = create_engine(
                "sqlite:///:memory:",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(
                f"sqlite:///{Path(self.db_path).resolve()}",
                connect_args={"check_same_thread": False, "timeout": 30.0},
            )
            with self.engine.begin() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.execute(text("PRAGMA busy_timeout=30000"))

        TranslationBase.metadata.create_all(self.engine)

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

        with Session(self.engine) as session:
            stmt = select(TranslationRecord).where(
                TranslationRecord.normalized_term == norm,
                TranslationRecord.target_lang == target_lang,
            )
            if source_lang:
                stmt = stmt.where(TranslationRecord.source_lang == source_lang)
            else:
                stmt = stmt.order_by(TranslationRecord.hit_count.desc())

            row = session.scalars(stmt).first()
            if row is None:
                return None

            row.hit_count += 1
            row.updated_at = datetime.now(timezone.utc)
            session.commit()

            return CachedTranslation(
                normalized_term=row.normalized_term,
                source_lang=row.source_lang,
                target_lang=row.target_lang,
                translated_term=row.translated_term,
                category=row.category,
                labels=json.loads(row.labels_json or "{}"),
                synonyms=json.loads(row.synonyms_json or "{}"),
                is_compound=bool(row.is_compound),
                source=row.source,
                hit_count=row.hit_count,
            )

    def upsert(self, record: CachedTranslation) -> None:
        """Insert or update a translation record via SQLAlchemy ORM upsert."""
        norm = self.normalize_term(record.normalized_term)
        if not norm:
            return

        now = datetime.now(timezone.utc)
        with Session(self.engine) as session:
            stmt = sqlite_insert(TranslationRecord).values(
                normalized_term=norm,
                source_lang=record.source_lang,
                target_lang=record.target_lang,
                translated_term=record.translated_term,
                category=record.category,
                labels_json=json.dumps(record.labels, ensure_ascii=False),
                synonyms_json=json.dumps(record.synonyms, ensure_ascii=False),
                is_compound=bool(record.is_compound),
                source=record.source,
                hit_count=record.hit_count,
                created_at=now,
                updated_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["normalized_term", "source_lang", "target_lang"],
                set_={
                    "translated_term": stmt.excluded.translated_term,
                    "category": func.coalesce(stmt.excluded.category, TranslationRecord.category),
                    "labels_json": stmt.excluded.labels_json,
                    "synonyms_json": stmt.excluded.synonyms_json,
                    "is_compound": stmt.excluded.is_compound,
                    "source": stmt.excluded.source,
                    "updated_at": now,
                },
            )
            session.execute(stmt)
            session.commit()

    def seed_from_dictionary(self, dictionary: Dict[str, List[str]]) -> None:
        """Seed SQLite cache idempotently from built-in bilingual dictionary."""
        now = datetime.now(timezone.utc)
        values = []
        for en_term, cs_variants in dictionary.items():
            norm = self.normalize_term(en_term)
            if not norm or not cs_variants:
                continue
            synonyms = {"cs": cs_variants[1:]} if len(cs_variants) > 1 else {}
            labels = {"en": [en_term], "cs": [cs_variants[0]]}
            values.append(
                {
                    "normalized_term": norm,
                    "source_lang": "en",
                    "target_lang": "cs",
                    "translated_term": cs_variants[0],
                    "category": None,
                    "labels_json": json.dumps(labels, ensure_ascii=False),
                    "synonyms_json": json.dumps(synonyms, ensure_ascii=False),
                    "is_compound": " " in norm,
                    "source": "dictionary",
                    "hit_count": 1,
                    "created_at": now,
                    "updated_at": now,
                }
            )

        if not values:
            return

        with Session(self.engine) as session:
            stmt = sqlite_insert(TranslationRecord).values(values).on_conflict_do_nothing(
                index_elements=["normalized_term", "source_lang", "target_lang"]
            )
            session.execute(stmt)
            session.commit()

    def count(self) -> int:
        """Return total number of cached translation entries."""
        with Session(self.engine) as session:
            total = session.scalar(select(func.count()).select_from(TranslationRecord))
            return int(total or 0)

    def close(self) -> None:
        """Dispose SQLAlchemy engine connection pool."""
        self.engine.dispose()


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
