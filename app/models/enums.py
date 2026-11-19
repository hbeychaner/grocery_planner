from enum import Enum


class StoreType(str, Enum):
    """Supported online grocery stores."""

    ROHLIK = "rohlik"
    KOSIK = "kosik"


class UnitType(str, Enum):
    """Standardized physical units of measurement."""

    KILOGRAM = "kg"
    GRAM = "g"
    LITER = "l"
    MILLILITER = "ml"
    PIECE = "pcs"
    UNKNOWN = "unknown"


class PriceAdvantage(str, Enum):
    """Comparison outcome between two stores."""

    ROHLIK_CHEAPER = "rohlik_cheaper"
    KOSIK_CHEAPER = "kosik_cheaper"
    TIED = "tied"
    UNAVAILABLE = "unavailable"
