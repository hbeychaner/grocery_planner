class GroceryComparatorException(Exception):
    """Base exception for grocery price comparator application."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class StoreClientException(GroceryComparatorException):
    """Raised when an external grocery store API encounters an error."""

    def __init__(self, store: str, message: str) -> None:
        super().__init__(f"[{store}] {message}")
        self.store = store


class ProductNotFoundException(GroceryComparatorException):
    """Raised when no matching products could be found in one or both stores."""

    def __init__(self, query: str) -> None:
        super().__init__(f"No products found matching '{query}'.")
        self.query = query


class StapleNotFoundException(GroceryComparatorException):
    """Raised when a requested staple identifier does not exist in configuration."""

    def __init__(self, staple_id: str) -> None:
        super().__init__(f"Staple with ID '{staple_id}' not found.")
        self.staple_id = staple_id
