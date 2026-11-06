"""Page and page_size query parameters, shared by every list endpoint."""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query

from app.core.config import get_settings


@dataclass(frozen=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def get_page_params(
    page: Annotated[int, Query(ge=1, description="Page number, starting at 1")] = 1,
    page_size: Annotated[int | None, Query(ge=1, description="Items per page")] = None,
) -> PageParams:
    settings = get_settings()
    size = (
        settings.DEFAULT_PAGE_SIZE
        if page_size is None
        else min(page_size, settings.MAX_PAGE_SIZE)
    )
    return PageParams(page=page, page_size=size)


PageDep = Annotated[PageParams, Depends(get_page_params)]


def paginated(items: list[Any], total: int, params: PageParams) -> dict[str, Any]:
    """The data part of every list response."""
    return {
        "items": items,
        "page": params.page,
        "page_size": params.page_size,
        "total": total,
    }
