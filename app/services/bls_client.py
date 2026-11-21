import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import httpx
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.services.price_history import PriceHistoryService, PriceSnapshotRecord

logger = logging.getLogger(__name__)

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
FRANKFURTER_URL = "https://api.frankfurter.dev/v1"

LB_TO_KG = 2.20462262
GAL_TO_L = 3.78541178

# Verified U.S. BLS Average Retail Food Price series -> (tracked_query, description, multiplier_to_metric, metric_unit, imperial_unit)
BLS_SERIES_MAP: Dict[str, Tuple[str, str, float, str, str]] = {
    "APU0000709112": ("whole milk", "Whole milk, fresh", 1.0 / GAL_TO_L, "l", "gal"),
    "APU0000708111": ("eggs", "Eggs, grade A, large", 1.0 / 12.0, "pcs", "doz"),
    "APU0000701111": ("plain flour", "Flour, white, all purpose", LB_TO_KG, "kg", "lb"),
    "APU0000701312": ("parboiled rice", "Rice, white, long grain", LB_TO_KG, "kg", "lb"),
    "APU0000702111": ("bread", "Bread, white", LB_TO_KG, "kg", "lb"),
    "APU0000706212": ("chicken thighs", "Chicken legs, bone-in", LB_TO_KG, "kg", "lb"),
    "APU0000FF1101": ("chicken breast", "Chicken breast, boneless", LB_TO_KG, "kg", "lb"),
    "APU0000711211": ("bananas", "Bananas", LB_TO_KG, "kg", "lb"),
    "APU0000711311": ("eating oranges", "Oranges, Navel", LB_TO_KG, "kg", "lb"),
    "APU0000712112": ("cooking potatoes", "Potatoes, white", LB_TO_KG, "kg", "lb"),
    "APU0000712311": ("vine tomatoes", "Tomatoes, field grown", LB_TO_KG, "kg", "lb"),
    "APU0000717311": ("ground coffee", "Coffee, 100% ground roast", LB_TO_KG, "kg", "lb"),
    "APU0000704111": ("bacon", "Bacon, sliced", LB_TO_KG, "kg", "lb"),
    "APU0000FS1101": ("butter", "Butter, salted", LB_TO_KG, "kg", "lb"),
}


class BlsIngestResult(BaseModel):
    """Summary of US BLS average food price ingestion with historical USD->CZK conversion."""

    series_fetched: int
    fx_months_loaded: int
    snapshots_inserted: int


class BlsPriceIngestionService:
    """Ingests U.S. BLS monthly retail food prices converted to CZK using historical ECB/Frankfurter FX rates."""

    def __init__(self, history: PriceHistoryService) -> None:
        self.history = history

    async def _fetch_monthly_usd_czk_rates(
        self, client: httpx.AsyncClient, start_year: int, end_year: int
    ) -> Dict[str, float]:
        """Fetch daily USD->CZK historical rates and average them per YYYY-MM."""
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        url = f"{FRANKFURTER_URL}/{start_year}-01-01..{end_date}"
        resp = await client.get(url, params={"base": "USD", "symbols": "CZK"})
        if resp.status_code != 200:
            logger.warning(f"Frankfurter FX API returned HTTP {resp.status_code}")
            return {}

        rates_by_day: Dict[str, Dict[str, float]] = resp.json().get("rates", {})
        monthly_buckets: Dict[str, List[float]] = {}
        for day_str, cur_map in rates_by_day.items():
            czk = cur_map.get("CZK")
            if czk is not None:
                ym = day_str[:7]
                monthly_buckets.setdefault(ym, []).append(float(czk))

        return {
            ym: round(sum(vals) / len(vals), 4)
            for ym, vals in monthly_buckets.items()
            if vals
        }

    async def ingest_all(self, start_year: int = 2025, end_year: int = 2026) -> BlsIngestResult:
        """Fetch BLS series and historical USD->CZK rates, convert to CZK/metric-unit, and store."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            fx_rates = await self._fetch_monthly_usd_czk_rates(client, start_year, end_year)
            fallback_fx = fx_rates[max(fx_rates.keys())] if fx_rates else 23.0

            payload = {
                "seriesid": list(BLS_SERIES_MAP.keys()),
                "startyear": str(start_year),
                "endyear": str(end_year),
            }
            resp = await client.post(BLS_API_URL, json=payload)
            if resp.status_code != 200:
                logger.warning(f"BLS API returned HTTP {resp.status_code}")
                return BlsIngestResult(series_fetched=0, fx_months_loaded=len(fx_rates), snapshots_inserted=0)

            body = resp.json()
            series_list = body.get("Results", {}).get("series", [])

        new_snapshots: List[PriceSnapshotRecord] = []
        series_with_data = 0

        for s in series_list:
            sid = s.get("seriesID", "")
            meta = BLS_SERIES_MAP.get(sid)
            if not meta:
                continue
            tracked_query, label, mult_to_metric, metric_unit, imp_unit = meta
            pts = s.get("data", [])
            has_any = False

            for pt in pts:
                val_str = pt.get("value")
                period = pt.get("period", "")
                year_str = pt.get("year", "")
                if not val_str or val_str == "-" or not period.startswith("M") or not year_str.isdigit():
                    continue
                month_num = int(period[1:])
                if month_num < 1 or month_num > 12:
                    continue

                usd_price = float(val_str)
                ym = f"{int(year_str):04d}-{month_num:02d}"
                fx = fx_rates.get(ym, fallback_fx)
                czk_pack = round(usd_price * fx, 2)
                czk_unit = round(usd_price * mult_to_metric * fx, 2)
                dt = datetime(int(year_str), month_num, 1, 0, 0, 0, tzinfo=timezone.utc)

                has_any = True
                new_snapshots.append(
                    PriceSnapshotRecord(
                        item_query=tracked_query,
                        store="bls",
                        product_id=f"bls_{sid}",
                        product_name=f"{label} (${usd_price:.2f}/{imp_unit} @ {fx:.2f} CZK/USD)",
                        brand="US BLS",
                        price=czk_pack,
                        unit_price=czk_unit,
                        unit_type=metric_unit,
                        is_on_sale=False,
                        is_bio=False,
                        recorded_at=dt,
                    )
                )

            if has_any:
                series_with_data += 1

        if new_snapshots:
            with Session(self.history.engine) as session:
                session.execute(
                    delete(PriceSnapshotRecord).where(PriceSnapshotRecord.store == "bls")
                )
                session.add_all(new_snapshots)
                session.commit()

        return BlsIngestResult(
            series_fetched=series_with_data,
            fx_months_loaded=len(fx_rates),
            snapshots_inserted=len(new_snapshots),
        )
