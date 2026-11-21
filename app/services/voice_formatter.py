from decimal import Decimal
from typing import Dict, Optional
from app.models.comparison import MatchedProductPair
from app.models.enums import PriceAdvantage, StoreType


class VoiceResponseFormatter:
    """Formats comparison results into concise, natural-sounding speech for Google Home."""

    def format_single_item_en(self, pair: Optional[MatchedProductPair], raw_query: str) -> str:
        """Create conversational English voice response."""
        if not pair:
            return f"Sorry, I couldn't find any matching products for '{raw_query}' on Rohlík or Košík."

        r_prod = pair.rohlik_product
        k_prod = pair.kosik_product

        if r_prod and not k_prod:
            unit_text = f" ({self._format_price(r_prod.unit_price)} per {r_prod.unit_type.value})" if r_prod.unit_price else ""
            return (
                f"{raw_query.capitalize()} is only available on Rohlik right now: "
                f"{r_prod.name} for {self._format_price(r_prod.price)} CZK{unit_text}."
            )

        if k_prod and not r_prod:
            unit_text = f" ({self._format_price(k_prod.unit_price)} per {k_prod.unit_type.value})" if k_prod.unit_price else ""
            return (
                f"{raw_query.capitalize()} is only available on Kosik right now: "
                f"{k_prod.name} for {self._format_price(k_prod.price)} CZK{unit_text}."
            )

        if not r_prod or not k_prod:
            return f"Sorry, I couldn't find a complete comparison for '{raw_query}'."

        if pair.advantage == PriceAdvantage.TIED:
            return (
                f"{raw_query.capitalize()} is the same price at both stores: "
                f"{r_prod.name} on Rohlik and {k_prod.name} on Kosik are both "
                f"{self._format_price(r_prod.price)} CZK."
            )

        winner_name = "Rohlik" if pair.cheaper_store == StoreType.ROHLIK else "Kosik"
        loser_name = "Kosik" if pair.cheaper_store == StoreType.ROHLIK else "Rohlik"
        winner_prod = r_prod if pair.cheaper_store == StoreType.ROHLIK else k_prod
        loser_prod = k_prod if pair.cheaper_store == StoreType.ROHLIK else r_prod

        diff = pair.price_difference
        pct = pair.percentage_savings

        if winner_prod.unit_price and loser_prod.unit_price:
            return (
                f"{winner_name} offers the best value for {raw_query.lower()} with {winner_prod.name} at "
                f"{self._format_price(winner_prod.price)} CZK, which is "
                f"{self._format_price(winner_prod.unit_price)} CZK per {winner_prod.unit_type.value}, "
                f"compared to {self._format_price(loser_prod.unit_price)} per {loser_prod.unit_type.value} on {loser_name}."
            )

        return (
            f"{winner_name} is cheaper for {raw_query.lower()} with {winner_prod.name} at "
            f"{self._format_price(winner_prod.price)} CZK compared to "
            f"{self._format_price(loser_prod.price)} CZK on {loser_name}, "
            f"saving you {self._format_price(diff)} CZK ({pct}%)."
        )

    def format_single_item_cs(self, pair: Optional[MatchedProductPair], term_cs: str) -> str:
        """Create conversational Czech voice response using strictly Czech terminology."""
        display_term = term_cs.strip()
        if not pair:
            return f"Bohužel jsem nenašel kompletní porovnání pro '{display_term}'."

        r_prod = pair.rohlik_product
        k_prod = pair.kosik_product

        if r_prod and not k_prod:
            unit_text = f" ({self._format_price(r_prod.unit_price)} Kč za {r_prod.unit_type.value})" if r_prod.unit_price else ""
            return (
                f"{display_term.capitalize()} je k dispozici pouze na Rohlíku: {r_prod.name} za "
                f"{self._format_price(r_prod.price)} Kč{unit_text}."
            )

        if k_prod and not r_prod:
            unit_text = f" ({self._format_price(k_prod.unit_price)} Kč za {k_prod.unit_type.value})" if k_prod.unit_price else ""
            return (
                f"{display_term.capitalize()} je k dispozici pouze na Košíku: {k_prod.name} za "
                f"{self._format_price(k_prod.price)} Kč{unit_text}."
            )

        if not r_prod or not k_prod:
            return f"Bohužel jsem nenašel kompletní porovnání pro '{display_term}'."

        if pair.advantage == PriceAdvantage.TIED:
            return (
                f"{display_term.capitalize()} stojí stejně v obou obchodech: "
                f"{r_prod.name} na Rohlíku i {k_prod.name} na Košíku stojí "
                f"{self._format_price(r_prod.price)} Kč."
            )

        winner = "Rohlík" if pair.cheaper_store == StoreType.ROHLIK else "Košík"
        loser = "Košíku" if pair.cheaper_store == StoreType.ROHLIK else "Rohlíku"
        winner_prod = r_prod if pair.cheaper_store == StoreType.ROHLIK else k_prod
        loser_prod = k_prod if pair.cheaper_store == StoreType.ROHLIK else r_prod

        if winner_prod.unit_price and loser_prod.unit_price:
            return (
                f"{winner} nabízí výhodnější {display_term.lower()} s produktem {winner_prod.name} za "
                f"{self._format_price(winner_prod.price)} Kč ({self._format_price(winner_prod.unit_price)} Kč za {winner_prod.unit_type.value}) "
                f"oproti {self._format_price(loser_prod.unit_price)} Kč na {loser}."
            )

        return (
            f"{winner} je levnější pro {display_term.lower()}: {winner_prod.name} stojí "
            f"{self._format_price(winner_prod.price)} Kč oproti "
            f"{self._format_price(loser_prod.price)} Kč na {loser}."
        )

    def format_by_language(
        self,
        pair: Optional[MatchedProductPair],
        translations: Dict[str, str],
        fallback_query: str,
    ) -> Dict[str, str]:
        """Generate language-keyed voice summaries for all supported languages."""
        term_en = translations.get("en", fallback_query)
        term_cs = translations.get("cs", fallback_query)
        return {
            "en": self.format_single_item_en(pair, term_en),
            "cs": self.format_single_item_cs(pair, term_cs),
        }

    @staticmethod
    def _format_price(value: Decimal) -> str:
        return f"{value:.2f}"
