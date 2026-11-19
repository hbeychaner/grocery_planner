from abc import ABC, abstractmethod
from typing import List, Optional
from app.models.enums import StoreType
from app.models.product import StoreProduct


class BaseStoreClient(ABC):
    """Abstract base class for grocery store clients."""

    @property
    @abstractmethod
    def store_type(self) -> StoreType:
        """Return the store identifier."""
        raise NotImplementedError

    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> List[StoreProduct]:
        """Search products on the store and return normalized StoreProduct list.
        
        Args:
            query: Product search query string in Czech.
            limit: Maximum number of products to return.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, product_id: str) -> Optional[StoreProduct]:
        """Fetch details of a single product by store product id."""
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify store availability."""
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """Clean up underlying HTTP sessions or resources."""
        raise NotImplementedError
