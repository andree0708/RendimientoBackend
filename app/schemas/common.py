"""Common shared schemas: pagination, timestamps, etc."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PageMeta(BaseModel):
    """Pagination metadata for list responses."""

    page: int
    page_size: int
    total: int
    total_pages: int


class Page(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    items: list[T]
    meta: PageMeta
