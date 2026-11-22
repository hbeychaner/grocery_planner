from pathlib import Path
from unittest.mock import MagicMock
import pytest

from app.services.relevance_dataset import (
    load_local_relevance_dataset,
    record_relevance_decision,
    run_relevance_experiment,
    score_index_prediction,
)


def test_record_and_load_relevance_dataset(tmp_path: Path) -> None:
    ds_file = tmp_path / "relevance.jsonl"
    mock_mon = MagicMock()
    mock_mon.is_active = True

    written = record_relevance_decision(
        query="blueberries",
        query_cs="borůvky",
        titles=["Activia Kefír borůvka", "Čerstvé borůvky 250g"],
        relevant_indices=[1],
        model="qwen3.5:latest",
        provider="ollama",
        monitoring=mock_mon,
        trace_id="trace-1",
        observation_id="obs-1",
        dataset_path=ds_file,
        langfuse_dataset_name="grocery-relevance-classification",
    )
    assert written == 2
    mock_mon.log_dataset_item.assert_called_once()
    assert mock_mon.record_score.call_count == 2

    loaded = load_local_relevance_dataset(dataset_path=ds_file)
    assert len(loaded) == 1
    assert loaded[0]["query"] == "blueberries"
    assert loaded[0]["relevant_indices"] == [1]


@pytest.mark.asyncio
async def test_run_relevance_experiment_local_fallback(tmp_path: Path) -> None:
    ds_file = tmp_path / "relevance.jsonl"
    record_relevance_decision(
        query="blueberries",
        query_cs="borůvky",
        titles=["Kefír borůvka", "Čerstvé borůvky"],
        relevant_indices=[1],
        model="qwen3.5:latest",
        provider="ollama",
        dataset_path=ds_file,
    )

    async def perfect_predictor(query: str, query_cs: str, titles: list[str]) -> list[int]:
        return [i for i, t in enumerate(titles) if "kefír" not in t.lower()]

    summary = await run_relevance_experiment(
        experiment_name="test-exp",
        run_name="perfect-run",
        predictor=perfect_predictor,
        dataset_path=ds_file,
    )
    assert summary.items_evaluated == 1
    assert summary.mean_f1 == 1.0
    assert summary.exact_match_rate == 1.0
    assert score_index_prediction([0, 1], [1])["precision"] == 0.5
