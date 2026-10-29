"""Shared pagination parameters and response envelope."""

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


class PageParams:
    def __init__(
        self,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        self.limit = limit
        self.offset = offset


class Page(BaseModel, Generic[T]):  # noqa: UP046 - keep Python 3.11 compatibility
    items: list[T]
    total: int
    limit: int
    offset: int
