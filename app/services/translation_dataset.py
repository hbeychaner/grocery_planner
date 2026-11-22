"""Translation dataset capture and Gemini accuracy annotation for Langfuse."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.monitoring import MonitoringService
from app.services.translation_cache import TranslationCacheService, TranslationRecord

logger = logging.getLogger(__name__)


class TranslationAnnotation(BaseModel):
    """Gemini evaluation of a grocery query translation."""

    is_accurate: bool
    accuracy_score: float = Field(ge=0.0, le=1.0)
    recommended_term: str
    reason: str


def record_translation_event(
    *,
    query: str,
    source_lang: str,
    target_lang: str,
    translated_term: str,
    category: Optional[str],
    model: str,
    provider: str,
    monitoring: Optional[MonitoringService] = None,
    trace_id: Optional[str] = None,
    observation_id: Optional[str] = None,
    dataset_path: Optional[Path] = None,
    langfuse_dataset_name: Optional[str] = None,
) -> None:
    """Append a translation record to local JSONL and Langfuse Dataset."""
    out_path = dataset_path or settings.translation_dataset_path
    now_iso = datetime.now(timezone.utc).isoformat()
    row = {
        "query": query,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "translated_term": translated_term,
        "category": category or "",
        "model": model,
        "provider": provider,
        "trace_id": trace_id,
        "recorded_at": now_iso,
    }
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug(f"Failed to append translation dataset row: {exc}")

    if monitoring is not None and monitoring.is_active:
        ds_name = langfuse_dataset_name or settings.langfuse_translation_dataset
        monitoring.log_dataset_item(
            dataset_name=ds_name,
            input_data={"query": query, "source_lang": source_lang, "target_lang": target_lang},
            expected_output={"translated_term": translated_term, "category": category},
            metadata={"model": model, "provider": provider},
            source_trace_id=trace_id,
            source_observation_id=observation_id,
        )


async def annotate_translation_with_gemini(
    llm: Any,
    *,
    query: str,
    source_lang: str,
    target_lang: str,
    current_translation: str,
) -> Optional[TranslationAnnotation]:
    """Use Gemini to score a grocery translation and recommend adjustments."""
    prompt = f"""Evaluate this Prague supermarket search translation ({source_lang} -> {target_lang}):
Source query: "{query}"
Current translation: "{current_translation}"

Rules for Prague online supermarkets (Rohlík.cz, Košík.cz):
- Search terms should be natural, common Czech grocery terms (not overly narrow adjectives like "brambory konzumní" when "brambory" works better).
- Score 1.0 if accurate and natural; 0.5-0.8 if understandable but awkward/too narrow; <0.5 if wrong.
Return ONLY valid JSON:
{{"is_accurate": true, "accuracy_score": 1.0, "recommended_term": "{current_translation}", "reason": "short explanation"}}"""

    resp = await llm.generate(
        [{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=200,
    )
    if not resp or not resp.text:
        return None
    try:
        data = llm._extract_json(resp.text)
        return TranslationAnnotation.model_validate(data)
    except Exception as exc:
        logger.debug(f"Failed to parse Gemini translation annotation for '{query}': {exc}")
        return None


async def backfill_and_annotate_translations(
    *,
    cache_service: TranslationCacheService,
    llm: Any,
    monitoring: Optional[MonitoringService] = None,
    limit: Optional[int] = None,
    dataset_path: Optional[Path] = None,
    langfuse_dataset_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Read existing translations from SQLite, annotate with Gemini, and store in Langfuse."""
    with Session(cache_service.engine) as session:
        stmt = select(TranslationRecord).order_by(TranslationRecord.normalized_term.asc())
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)
        records = session.scalars(stmt).all()

    out_path = dataset_path or settings.translation_dataset_path
    ds_name = langfuse_dataset_name or settings.langfuse_translation_dataset
    annotated_count = 0
    adjustments: List[Dict[str, Any]] = []

    for rec in records:
        with (
            monitoring.trace_generation(
                name="annotate-translation-accuracy",
                model=llm.model,
                input_data={
                    "query": rec.normalized_term,
                    "source_lang": rec.source_lang,
                    "target_lang": rec.target_lang,
                    "current_translation": rec.translated_term,
                },
                flush_on_exit=False,
            )
            if monitoring is not None and monitoring.is_active
            else _null_ctx()
        ) as span:
            ann = await annotate_translation_with_gemini(
                llm,
                query=rec.normalized_term,
                source_lang=rec.source_lang,
                target_lang=rec.target_lang,
                current_translation=rec.translated_term,
            )
            if ann is None:
                continue
            annotated_count += 1
            if ann.recommended_term.strip().lower() != rec.translated_term.strip().lower():
                adjustments.append(
                    {
                        "query": rec.normalized_term,
                        "current": rec.translated_term,
                        "recommended": ann.recommended_term,
                        "score": ann.accuracy_score,
                        "reason": ann.reason,
                    }
                )

            trace_id = getattr(span, "trace_id", None) if span is not None else None
            obs_id = getattr(span, "id", None) if span is not None else None
            if span is not None:
                span.update(output=ann.model_dump())
            if monitoring is not None and monitoring.is_active:
                monitoring.log_dataset_item(
                    dataset_name=ds_name,
                    input_data={
                        "query": rec.normalized_term,
                        "source_lang": rec.source_lang,
                        "target_lang": rec.target_lang,
                        "current_translation": rec.translated_term,
                    },
                    expected_output=ann.model_dump(),
                    metadata={"category": rec.category, "annotator_model": llm.model},
                    source_trace_id=trace_id,
                    source_observation_id=obs_id,
                )
                monitoring.record_score(
                    name="translation_accuracy",
                    value=ann.accuracy_score,
                    trace_id=trace_id,
                    observation_id=obs_id,
                    data_type="NUMERIC",
                    comment=ann.reason,
                )

            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {
                                "query": rec.normalized_term,
                                "source_lang": rec.source_lang,
                                "target_lang": rec.target_lang,
                                "current_translation": rec.translated_term,
                                **ann.model_dump(),
                                "annotator_model": llm.model,
                                "recorded_at": datetime.now(timezone.utc).isoformat(),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            except Exception:
                pass

    if monitoring is not None:
        monitoring.flush()

    return {
        "total_records": len(records),
        "annotated": annotated_count,
        "adjustments_recommended": len(adjustments),
        "sample_adjustments": adjustments[:10],
    }


class _null_ctx:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: Any) -> bool:
        return False
