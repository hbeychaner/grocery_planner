from decimal import Decimal
from typing import Optional
from app.models.enums import PriceAdvantage, StoreType
from app.models.comparison import MatchedProductPair


class VoiceResponseFormatter:
    """Formats comparison results into natural speech strings for Google Home / IFTTT."""

    def format_single_item_en(self, pair: Optional[MatchedProductPair], raw_query: str) -> str:
        """Create conversational English voice response highlighting unit pricing."""
        if not pair:
            return f"I couldn't find any products matching '{raw_query}' on Rohlik or Kosik."

        r_prod = pair.rohlik_product
        k_prod = pair.kosik_product

        if r_prod and not k_prod:
            sale_text = " (currently on sale)" if r_prod.is_on_sale else ""
            unit_str = r_prod.unit_type.value if hasattr(r_prod.unit_type, "value") else str(r_prod.unit_type)
            unit_text = f" ({self._format_price(r_prod.unit_price)} per {unit_str})" if r_prod.unit_price else ""
            return (
                f"{raw_query.capitalize()} is only available on Rohlik: {r_prod.name} for "
                f"{self._format_price(r_prod.price)} CZK{unit_text}{sale_text}."
            )

        if k_prod and not r_prod:
            sale_text = " (currently on sale)" if k_prod.is_on_sale else ""
            unit_str = k_prod.unit_type.value if hasattr(k_prod.unit_type, "value") else str(k_prod.unit_type)
            unit_text = f" ({self._format_price(k_prod.unit_price)} per {unit_str})" if k_prod.unit_price else ""
            return (
                f"{raw_query.capitalize()} is only available on Kosik: {k_prod.name} for "
                f"{self._format_price(k_prod.price)} CZK{unit_text}{sale_text}."
            )

        if not r_prod or not k_prod:
            return f"I couldn't find price data for '{raw_query}'."

        if pair.advantage == PriceAdvantage.TIED:
            unit_str = r_prod.unit_type.value if hasattr(r_prod.unit_type, "value") else str(r_prod.unit_type)
            unit_text = f" ({self._format_price(r_prod.unit_price)} per {unit_str})" if r_prod.unit_price else ""
            return (
                f"Both stores offer the same price for {raw_query} at "
                f"{self._format_price(r_prod.price)} CZK{unit_text}."
            )

        winner_name = "Rohlik" if pair.cheaper_store == StoreType.ROHLIK else "Kosik"
        loser_name = "Kosik" if pair.cheaper_store == StoreType.ROHLIK else "Rohlik"
        winner_prod = r_prod if pair.cheaper_store == StoreType.ROHLIK else k_prod
        loser_prod = k_prod if pair.cheaper_store == StoreType.ROHLIK else r_prod

        # Include per kg/unit information if available
        if winner_prod.unit_price and loser_prod.unit_price and winner_prod.unit_type == loser_prod.unit_type:
            unit_str = winner_prod.unit_type.value
            return (
                f"{winner_name} offers the best value for {raw_query} with {winner_prod.name} at "
                f"{self._format_price(winner_prod.price)} CZK, which is {self._format_price(winner_prod.unit_price)} CZK per {unit_str}, "
                f"compared to {self._format_price(loser_prod.unit_price)} per {unit_str} on {loser_name}."
            )

        diff = pair.price_difference
        pct = pair.percentage_savings

        return (
            f"{winner_name} is cheaper for {raw_query} with {winner_prod.name} at "
            f"{self._format_price(winner_prod.price)} CZK compared to "
            f"{self._format_price(loser_prod.price)} CZK on {loser_name}, "
            f"saving you {self._format_price(diff)} CZK ({pct}%)."
        )

    def format_single_item_cs(self, pair: Optional[MatchedProductPair], raw_query: str) -> str:
        """Create conversational Czech voice response."""
        if not pair:
            return f"Bohužel jsem nenašel kompletní porovnání pro '{raw_query}'."

        r_prod = pair.rohlik_product
        k_prod = pair.kosik_product

        if r_prod and not k_prod:
            unit_text = f" ({self._format_price(r_prod.unit_price)} Kč za {r_prod.unit_type.value})" if r_prod.unit_price else ""
            return (
                f"{raw_query.capitalize()} je k dispozici pouze na Rohlíku: {r_prod.name} za "
                f"{self._format_price(r_prod.price)} Kč{unit_text}."
            )

        if k_prod and not r_prod:
            unit_text = f" ({self._format_price(k_prod.unit_price)} Kč za {k_prod.unit_type.value})" if k_prod.unit_price else ""
            return (
                f"{raw_query.capitalize()} je k dispozici pouze na Košíku: {k_prod.name} za "
                f"{self._format_price(k_prod.price)} Kč{unit_text}."
            )

        if not r_prod or not k_prod:
            return f"Bohužel jsem nenašel kompletní porovnání pro '{raw_query}'."

        winner = "Rohlík" if pair.cheaper_store == StoreType.ROHLIK else "Košík"
        loser = "Košíku" if pair.cheaper_store == StoreType.ROHLIK else "Rohlíku"
        winner_prod = r_prod if pair.cheaper_store == StoreType.ROHLIK else k_prod
        loser_prod = k_prod if pair.cheaper_store == StoreType.ROHLIK else r_prod

        if winner_prod.unit_price and loser_prod.unit_price:
            return (
                f"{winner} nabízí výhodnější {raw_query} s produktem {winner_prod.name} za "
                f"{self._format_price(winner_prod.price)} Kč ({self._format_price(winner_prod.unit_price)} Kč za {winner_prod.unit_type.value}) "
                f"oproti {self._format_price(loser_prod.unit_price)} Kč na {loser}."
            )

        return (
            f"{winner} je levnější pro {raw_query}: {winner_prod.name} stojí "
            f"{self._format_price(winner_prod.price)} Kč oproti "
            f"{self._format_price(loser_prod.price)} Kč na {loser}."
        )

    @staticmethod
    def _format_price(amount: Decimal) -> str:
        return f"{amount:.2f}"
