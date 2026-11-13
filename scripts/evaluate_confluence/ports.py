"""Interfaces for evaluator services and their external dependencies."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, AsyncContextManager, Protocol

from .config import Settings


class ConfluenceGateway(Protocol):
    def close(self) -> None: ...

    def get_spaces(self) -> list[dict[str, Any]]: ...

    def get_pages(self) -> list[dict[str, Any]]: ...

    def get_page_detail(
        self, page_id: str, body_format: str = "storage"
    ) -> dict[str, Any]: ...

    def get_page_comments(self, page_id: str) -> list[str]: ...

    def get_likes_count(self, page_id: str) -> int: ...

    def page_url(self, page: dict[str, Any]) -> str: ...


class PageAnalyzer(Protocol):
    async def analyze_structure(self, page: dict[str, Any]) -> dict[str, Any]: ...

    async def classify_comments(
        self, page_title: str, comments: list[str]
    ) -> dict[int, tuple[str, float]]: ...


class EvaluationRepository(Protocol):
    def close(self) -> None: ...

    def persist(
        self,
        spaces: list[dict[str, Any]],
        pages: list[dict[str, Any]],
        evaluation_date: date,
        model: str,
    ) -> None: ...


ConfluenceFactory = Callable[[Settings], ConfluenceGateway]
CopilotFactory = Callable[
    [str, str], AsyncContextManager[PageAnalyzer]
]
RepositoryFactory = Callable[[str], EvaluationRepository]
