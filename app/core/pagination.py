"""Pagination helper utilities."""

from typing import Any

from fastapi import Query

from app.schemas.common import Page, PageMeta


class PaginationParams:
    """Reusable FastAPI dependency for pagination query parameters."""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    ):
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def paginate(items: list[Any], total: int, pagination: PaginationParams) -> Page:
    """Build a Page response from a slice of items and the total count."""
    total_pages = (total + pagination.page_size - 1) // pagination.page_size if pagination.page_size else 1
    return Page(
        items=items,
        meta=PageMeta(
            page=pagination.page,
            page_size=pagination.page_size,
            total=total,
            total_pages=total_pages,
        ),
    )
