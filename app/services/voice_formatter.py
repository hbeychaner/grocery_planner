from decimal import Decimal
from typing import Optional
from app.models.enums import PriceAdvantage, StoreType
from app.models.comparison import MatchedProductPair


class VoiceResponseFormatter:
    """Formats comparison results into natural speech strings for Google Home / IFTTT."""

    def format_single_item_en(self, pair: Optional[MatchedProductPair], raw_query: str) -> str:
        """Create conversational English voice response."""
        if not pair:
            return f"I couldn't find any products matching '{raw_query}' on Rohlik or Kosik."

        r_prod = pair.rohlik_product
        k_prod = pair.kosik_product

        # If only Rohlik has it
        if r_prod and not k_prod:
            sale_text = " (currently on sale)" if r_prod.is_on_sale else ""
            return (
                f"{raw_query.capitalize()} is only available on Rohlik for "
                f"{self._format_price(r_prod.price)} CZK{sale_text}."
            )

        # If only Kosik has it
        if k_prod and not r_prod:
            sale_text = " (currently on sale)" if k_prod.is_on_sale else ""
            return (
                f"{raw_query.capitalize()} is only available on Kosik for "
                f"{self._format_price(k_prod.price)} CZK{sale_text}."
            )

        if not r_prod or not k_prod:
            return f"I couldn't find price data for '{raw_query}'."

        # Both have it
        if pair.advantage == PriceAdvantage.TIED:
            return (
                f"Both stores offer the same price for {raw_query} at "
                f"{self._format_price(r_prod.price)} CZK."
            )

        winner_name = "Rohlik" if pair.cheaper_store == StoreType.ROHLIK else "Kosik"
        loser_name = "Kosik" if pair.cheaper_store == StoreType.ROHLIK else "Rohlik"
        winner_price = r_prod.price if pair.cheaper_store == StoreType.ROHLIK else k_prod.price
        loser_price = k_prod.price if pair.cheaper_store == StoreType.ROHLIK else r_prod.price

        diff = pair.price_difference
        pct = pair.percentage_savings

        return (
            f"{winner_name} is cheaper for {raw_query}. "
            f"It costs {self._format_price(winner_price)} CZK compared to "
            f"{self._format_price(loser_price)} CZK on {loser_name}, "
            f"saving you {self._format_price(diff)} CZK, or {pct} percent."
        )

    def format_single_item_cs(self, pair: Optional[MatchedProductPair], raw_query: str) -> str:
        """Create conversational Czech voice response."""
        if not pair:
            return f"Bohužel jsem nenašel žádné produkty pro '{raw_query}' na Rohlíku ani Košíku."

        r_prod = pair.rohlik_product
        k_prod = pair.kosik_product

        if r_prod and not k_prod:
            return f"Zboží '{raw_query}' je dostupné pouze na Rohlíku za {self._format_price(r_prod.price)} Kč."

        if k_prod and not r_prod:
            return f"Zboží '{raw_query}' je dostupné pouze na Košíku za {self._format_price(k_prod.price)} Kč."

        if not r_prod or not k_prod:
            return f"Ceny pro '{raw_query}' nejsou dostupné."

        if pair.advantage == PriceAdvantage.TIED:
            return f"Oba obchody nabízejí stejnou cenu {self._format_price(r_prod.price)} Kč."

        winner = "Rohlík" if pair.cheaper_store == StoreType.ROHLIK else "Košík"
        loser = "Košíku" if pair.cheaper_store == StoreType.ROHLIK else "Rohlíku"
        winner_price = r_prod.price if pair.cheaper_store == StoreType.ROHLIK else k_prod.price
        loser_price = k_prod.price if pair.cheaper_store == StoreType.ROHLIK else r_prod.price
        diff = pair.price_difference

        return (
            f"{winner} je levnější pro {raw_query}. "
            f"Stojí {self._format_price(winner_price)} Kč oproti "
            f"{self._format_price(loser_price)} Kč na {loser}, "
            f"ušetříte {self._format_price(diff)} Kč."
        )

    @staticmethod
    def _format_price(amount: Decimal) -> str:
        """Format decimal to standard currency string with 2 decimal places."""
        return f"{amount:.2f}"
