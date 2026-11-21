import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import httpx
from pydantic import BaseModel

from app.services.matcher import ProductMatchingService
from app.services.price_history import PriceHistoryService, PriceSnapshotRecord, TrackedItemRecord
from sqlalchemy import delete
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

CSU_BASE_URL = "https://data.csu.gov.cz/api/dotaz/v1/data/vybery"
CSU_DATASETS = ["CEN0101DT01", "CEN0101NT01"]

CZECH_MONTHS: Dict[str, int] = {
    "leden": 1,
    "únor": 2,
    "březen": 3,
    "duben": 4,
    "květen": 5,
    "červen": 6,
    "červenec": 7,
    "srpen": 8,
    "září": 9,
    "říjen": 10,
    "listopad": 11,
    "prosinec": 12,
}


class CsuIngestResult(BaseModel):
    """Summary of ČSÚ historical price ingestion."""

    datasets_fetched: int
    csu_items_matched: int
    snapshots_inserted: int


class CsuPriceIngestionService:
    """Ingests official Czech Statistical Office (ČSÚ) monthly average grocery prices."""

    def __init__(
        self,
        history: PriceHistoryService,
        matcher: Optional[ProductMatchingService] = None,
    ) -> None:
        self.history = history
        self.matcher = matcher or ProductMatchingService()

    @staticmethod
    def _parse_czech_month(label: str) -> Optional[datetime]:
        """Parse 'leden 2026' -> datetime(2026, 1, 1, tzinfo=utc)."""
        parts = label.strip().lower().split()
        if len(parts) != 2:
            return None
        month_num = CZECH_MONTHS.get(parts[0])
        if not month_num or not parts[1].isdigit():
            return None
        return datetime(int(parts[1]), month_num, 1, 0, 0, 0, tzinfo=timezone.utc)

    @staticmethod
    def _parse_item_label(label: str) -> Tuple[str, float, str]:
        """Extract clean Czech name and unit multiplier from e.g. 'Máslo [250 g]' -> ('Máslo', 4.0, 'kg')."""
        match = re.search(r"\[([^\]]+)\]\s*$", label)
        clean_name = re.sub(r"\s*\[[^\]]+\]\s*$", "", label).strip()
        if not match:
            return clean_name, 1.0, "kg"

        unit_spec = match.group(1).strip().lower().replace(",", ".")
        num_match = re.search(r"(\d+(?:\.\d+)?)", unit_spec)
        qty = float(num_match.group(1)) if num_match else 1.0

        if "kg" in unit_spec:
            return clean_name, (1.0 / qty if qty > 0 else 1.0), "kg"
        if "g" in unit_spec:
            return clean_name, (1000.0 / qty if qty > 0 else 1.0), "kg"
        if "ml" in unit_spec:
            return clean_name, (1000.0 / qty if qty > 0 else 1.0), "l"
        if "l" in unit_spec:
            return clean_name, (1.0 / qty if qty > 0 else 1.0), "l"
        if "ks" in unit_spec:
            return clean_name, (1.0 / qty if qty > 0 else 1.0), "pcs"
        return clean_name, 1.0, "kg"

    def _match_tracked_query(
        self, csu_name: str, tracked_items: List[Tuple[str, Optional[str]]]
    ) -> Optional[str]:
        """Pair a ČSÚ item name to the closest tracked grocery using spaCy lemmas + semantic similarity."""
        csu_lemmas = self.matcher.get_lemmas(csu_name, "cs")
        best_query: Optional[str] = None
        best_score = 0.0

        for query, query_cs in tracked_items:
            target = query_cs or query
            t_lemmas = self.matcher.get_lemmas(target, "cs")
            if not t_lemmas:
                continue

            # Require strong lemma overlap or high semantic similarity
            overlap = len(csu_lemmas & t_lemmas)
            if t_lemmas <= csu_lemmas:
                score = 0.85 + (0.15 * len(t_lemmas) / max(len(csu_lemmas), 1))
            elif overlap > 0:
                score = self.matcher.compute_similarity(target, csu_name)
            else:
                continue

            if score > best_score:
                best_score = score
                best_query = query

        return best_query if best_score >= 0.55 else None

    async def ingest_all(self) -> CsuIngestResult:
        """Fetch CEN0101DT01 and CEN0101NT01 from ČSÚ DataStat API and store normalized history."""
        tracked_items = [
            (item.query, item.query_cs)
            for item in self.history.list_tracked_items(active_only=True)
        ]

        datasets_fetched = 0
        matched_csu_codes = set()
        new_snapshots: List[PriceSnapshotRecord] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for code in CSU_DATASETS:
                url = f"{CSU_BASE_URL}/{code}?format=JSON_STAT"
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"ČSÚ dataset {code} returned HTTP {resp.status_code}")
                    continue

                datasets_fetched += 1
                data = resp.json()
                dims = data.get("dimension", {})
                item_dim = dims.get("CENREP4", {}).get("category", {})
                time_dim = dims.get("CasM", {}).get("category", {})

                item_labels: Dict[str, str] = item_dim.get("label", {})
                item_index: Dict[str, int] = item_dim.get("index", {})
                time_labels: Dict[str, str] = time_dim.get("label", {})
                time_index: Dict[str, int] = time_dim.get("index", {})
                values: List[Optional[float]] = data.get("value", [])
                n_months = len(time_index)

                # Reverse index maps
                idx_to_time: Dict[int, datetime] = {}
                for t_code, t_idx in time_index.items():
                    dt = self._parse_czech_month(time_labels.get(t_code, ""))
                    if dt is not None:
                        idx_to_time[int(t_idx)] = dt

                for item_code, raw_label in item_labels.items():
                    clean_name, multiplier, unit_type = self._parse_item_label(raw_label)
                    matched_query = self._match_tracked_query(clean_name, tracked_items)
                    if not matched_query:
                        continue

                    matched_csu_codes.add(item_code)
                    i_idx = int(item_index[item_code])

                    for t_idx, dt in idx_to_time.items():
                        flat_idx = i_idx * n_months + t_idx
                        if flat_idx >= len(values):
                            continue
                        raw_val = values[flat_idx]
                        if raw_val is None:
                            continue

                        pack_price = float(raw_val)
                        unit_price = round(pack_price * multiplier, 2)
                        new_snapshots.append(
                            PriceSnapshotRecord(
                                item_query=matched_query,
                                store="csu",
                                product_id=f"csu_{item_code}",
                                product_name=f"{raw_label} (ČSÚ Avg)",
                                brand="ČSÚ",
                                price=pack_price,
                                unit_price=unit_price,
                                unit_type=unit_type,
                                is_on_sale=False,
                                is_bio=False,
                                recorded_at=dt,
                            )
                        )

        if new_snapshots:
            with Session(self.history.engine) as session:
                # Replace previous ČSÚ snapshots idempotently so re-runs never duplicate months
                session.execute(
                    delete(PriceSnapshotRecord).where(PriceSnapshotRecord.store == "csu")
                )
                session.add_all(new_snapshots)
                session.commit()

        return CsuIngestResult(
            datasets_fetched=datasets_fetched,
            csu_items_matched=len(matched_csu_codes),
            snapshots_inserted=len(new_snapshots),
        )
