"""Relevance classification dataset capture, Langfuse scoring, and experiment runner.

Captures every LLM relevance-filtering decision into:
  1. Local JSONL training file (``data/relevance_training.jsonl``) with per-candidate
     binary labels (``is_relevant``) for training a lightweight non-LLM classifier.
  2. Langfuse Dataset (``grocery-relevance-classification``) linked to the source
     trace/observation, plus automatic Langfuse Scores (``kept_ratio``, ``non_empty_match``).
  3. Langfuse Experiment runner (``run_relevance_experiment``) to benchmark non-LLM
     baselines (spaCy/MiniLM) vs. Ollama vs. Gemini on Precision, Recall, F1, and Latency.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from langfuse.experiment import Evaluation, LocalExperimentItem
from pydantic import BaseModel

from app.core.config import settings
from app.services.monitoring import MonitoringService

logger = logging.getLogger(__name__)


class RelevanceExperimentSummary(BaseModel):
    """Summary metrics from evaluating a relevance classifier against the dataset."""

    experiment_name: str
    run_name: str
    items_evaluated: int
    mean_precision: float
    mean_recall: float
    mean_f1: float
    exact_match_rate: float


def record_relevance_decision(
    *,
    query: str,
    query_cs: Optional[str],
    titles: List[str],
    relevant_indices: List[int],
    model: str,
    provider: str,
    monitoring: Optional[MonitoringService] = None,
    trace_id: Optional[str] = None,
    observation_id: Optional[str] = None,
    dataset_path: Optional[Path] = None,
    langfuse_dataset_name: Optional[str] = None,
) -> int:
    """Persist relevance classification input/output locally (JSONL) and in Langfuse."""
    if not titles:
        return 0

    relevant_set = set(relevant_indices)
    now_iso = datetime.now(timezone.utc).isoformat()
    out_path = dataset_path or settings.relevance_dataset_path

    # 1. Append per-candidate binary classification examples to local JSONL for small-model training
    written = 0
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "a", encoding="utf-8") as f:
            for idx, title in enumerate(titles):
                row = {
                    "query": query,
                    "query_cs": query_cs or "",
                    "title": title,
                    "is_relevant": idx in relevant_set,
                    "model": model,
                    "provider": provider,
                    "trace_id": trace_id,
                    "recorded_at": now_iso,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
    except Exception as exc:
        logger.debug(f"Failed to append relevance training rows: {exc}")

    # 2. Log structured item to Langfuse Dataset + record telemetry scores
    if monitoring is not None and monitoring.is_active:
        ds_name = langfuse_dataset_name or settings.langfuse_relevance_dataset
        monitoring.log_dataset_item(
            dataset_name=ds_name,
            input_data={"query": query, "query_cs": query_cs or "", "titles": titles},
            expected_output={"relevant_indices": sorted(relevant_set)},
            metadata={"model": model, "provider": provider, "candidate_count": len(titles)},
            source_trace_id=trace_id,
            source_observation_id=observation_id,
        )
        kept_ratio = round(len(relevant_set) / len(titles), 4)
        monitoring.record_score(
            name="kept_ratio",
            value=kept_ratio,
            trace_id=trace_id,
            observation_id=observation_id,
            data_type="NUMERIC",
            comment=f"{len(relevant_set)}/{len(titles)} candidates kept by {model}",
        )
        monitoring.record_score(
            name="non_empty_match",
            value=1.0 if relevant_set else 0.0,
            trace_id=trace_id,
            observation_id=observation_id,
            data_type="BOOLEAN",
        )

    return written


def load_local_relevance_dataset(dataset_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Group local JSONL rows back into batch items ``{query, query_cs, titles, relevant_indices}``."""
    path = dataset_path or settings.relevance_dataset_path
    if not path.exists():
        return []

    grouped: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            key = (row.get("query", ""), row.get("query_cs", ""), row.get("recorded_at", ""))
            bucket = grouped.setdefault(
                key,
                {
                    "query": row.get("query", ""),
                    "query_cs": row.get("query_cs", ""),
                    "titles": [],
                    "relevant_indices": [],
                },
            )
            idx = len(bucket["titles"])
            bucket["titles"].append(row.get("title", ""))
            if row.get("is_relevant"):
                bucket["relevant_indices"].append(idx)
    return list(grouped.values())


def score_index_prediction(predicted: List[int], expected: List[int]) -> Dict[str, float]:
    """Compute precision, recall, F1, and exact match between predicted and expected index sets."""
    pred_set = set(predicted)
    exp_set = set(expected)
    if not pred_set and not exp_set:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "exact_match": 1.0}
    if not pred_set or not exp_set:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "exact_match": 0.0}

    tp = len(pred_set & exp_set)
    precision = tp / len(pred_set)
    recall = tp / len(exp_set)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    exact = 1.0 if pred_set == exp_set else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "exact_match": exact,
    }


async def run_relevance_experiment(
    *,
    experiment_name: str,
    run_name: str,
    predictor: Callable[[str, str, List[str]], Awaitable[List[int]]],
    monitoring: Optional[MonitoringService] = None,
    dataset_path: Optional[Path] = None,
    langfuse_dataset_name: Optional[str] = None,
    max_items: Optional[int] = None,
) -> RelevanceExperimentSummary:
    """Evaluate a relevance predictor via Langfuse Experiments (or local fallback)."""
    raw_items = load_local_relevance_dataset(dataset_path=dataset_path)
    if max_items is not None and max_items > 0:
        raw_items = raw_items[:max_items]

    if not raw_items:
        return RelevanceExperimentSummary(
            experiment_name=experiment_name,
            run_name=run_name,
            items_evaluated=0,
            mean_precision=0.0,
            mean_recall=0.0,
            mean_f1=0.0,
            exact_match_rate=0.0,
        )

    precisions: List[float] = []
    recalls: List[float] = []
    f1s: List[float] = []
    exacts: List[float] = []

    if monitoring is not None and monitoring.is_active and monitoring.client is not None:
        ds_name = langfuse_dataset_name or settings.langfuse_relevance_dataset
        try:
            dataset = monitoring.client.get_dataset(ds_name)
            data_items: Any = dataset.items[:max_items] if max_items else dataset.items
        except Exception:
            data_items = [
                LocalExperimentItem(
                    input={"query": it["query"], "query_cs": it["query_cs"], "titles": it["titles"]},
                    expected_output={"relevant_indices": it["relevant_indices"]},
                )
                for it in raw_items
            ]

        async def _lf_task(*, item: Any, **kwargs: Any) -> Dict[str, List[int]]:
            inp = item.input if hasattr(item, "input") else item["input"]
            preds = await predictor(inp["query"], inp.get("query_cs", ""), inp["titles"])
            return {"relevant_indices": preds}

        def _lf_evaluator(*, output: Any, expected_output: Any, **kwargs: Any) -> List[Evaluation]:
            pred_idx = (output or {}).get("relevant_indices", [])
            exp_idx = (expected_output or {}).get("relevant_indices", [])
            m = score_index_prediction(pred_idx, exp_idx)
            precisions.append(m["precision"])
            recalls.append(m["recall"])
            f1s.append(m["f1"])
            exacts.append(m["exact_match"])
            return [
                Evaluation(name="f1", value=m["f1"]),
                Evaluation(name="precision", value=m["precision"]),
                Evaluation(name="recall", value=m["recall"]),
                Evaluation(name="exact_match", value=m["exact_match"]),
            ]

        monitoring.client.run_experiment(
            name=experiment_name,
            run_name=run_name,
            data=data_items,
            task=_lf_task,
            evaluators=[_lf_evaluator],
            max_concurrency=1,
        )
        monitoring.flush()
    else:
        for it in raw_items:
            preds = await predictor(it["query"], it["query_cs"], it["titles"])
            m = score_index_prediction(preds, it["relevant_indices"])
            precisions.append(m["precision"])
            recalls.append(m["recall"])
            f1s.append(m["f1"])
            exacts.append(m["exact_match"])

    n = len(f1s) or 1
    return RelevanceExperimentSummary(
        experiment_name=experiment_name,
        run_name=run_name,
        items_evaluated=len(f1s),
        mean_precision=round(sum(precisions) / n, 4),
        mean_recall=round(sum(recalls) / n, 4),
        mean_f1=round(sum(f1s) / n, 4),
        exact_match_rate=round(sum(exacts) / n, 4),
    )
