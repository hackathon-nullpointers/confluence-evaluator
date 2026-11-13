"""Application orchestration for a daily Confluence evaluation run."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from spellchecker import SpellChecker

from .config import EvaluationError, Settings
from .confluence import ConfluenceClient
from .copilot import CopilotEvaluator
from .database import EvaluationDatabase
from .documents import extract_item_document, storage_value
from .link_checker import check_links, normalize_web_links
from .ports import (
    ConfluenceFactory,
    ConfluenceGateway,
    CopilotFactory,
    RepositoryFactory,
)
from .scoring import (
    comment_metrics,
    create_spell_checker,
    get_updated_at,
    prepare_scores,
    spelling_counts,
)

LinkChecker = Callable[[list[str]], tuple[int, int, int]]


def _profile_value(profile: dict[str, Any], key: str) -> str | None:
    value = profile.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def collect_page_work(
    api: ConfluenceGateway,
    pages: list[dict[str, Any]],
    spaces_by_id: dict[str, dict[str, Any]],
    spell_checker: SpellChecker,
    link_checker: LinkChecker = check_links,
) -> list[dict[str, Any]]:
    work: list[dict[str, Any]] = []
    user_profiles: dict[str, dict[str, Any] | None] = {}

    def author_profile(account_id: str | None) -> dict[str, Any] | None:
        if not account_id:
            return None
        if account_id not in user_profiles:
            try:
                user_profiles[account_id] = api.get_user(account_id)
            except EvaluationError as error:
                user_profiles[account_id] = None
                print(
                    f"Advertencia: no se pudo consultar el perfil del autor "
                    f"{account_id}: {error}",
                    file=sys.stderr,
                )
        return user_profiles[account_id]

    for page in pages:
        page_id = str(page.get("id", ""))
        space_id = str(page.get("spaceId", ""))
        space = spaces_by_id.get(space_id)
        if not page_id or not space:
            raise EvaluationError(
                f"No se pudo resolver el espacio de la página {page_id or '(sin id)'}."
            )

        author_account_id = page.get("authorId") or (
            page.get("version", {}).get("authorId")
            if isinstance(page.get("version"), dict)
            else None
        )
        author_account_id = str(author_account_id) if author_account_id else None
        entry: dict[str, Any] = {
            "page_id": page_id,
            "space_id": space_id,
            "space_key": str(space.get("key", "")),
            "space_name": str(space.get("name", "")),
            "title": str(page.get("title", "")),
            "page_url": api.page_url(page),
            "confluence_status": str(page.get("status", "current")),
            "author_account_id": author_account_id,
            "author_display_name": None,
            "author_email": None,
            "updated_at": None,
            "document": None,
            "comments": [],
            "likes_count": None,
            "word_count": None,
            "spelling_errors_count": None,
            "valid_links_count": None,
            "invalid_links_count": None,
            "unchecked_links_count": None,
            "failure": None,
        }
        profile = author_profile(author_account_id)
        if profile:
            entry["author_display_name"] = _profile_value(
                profile, "displayName"
            ) or _profile_value(profile, "publicName")
            entry["author_email"] = _profile_value(profile, "email")
        try:
            detail = page
            if not storage_value(detail) or not isinstance(detail.get("version"), dict):
                detail = api.get_page_detail(page_id)
            if not entry["author_account_id"]:
                version = detail.get("version")
                entry["author_account_id"] = detail.get("authorId") or (
                    version.get("authorId") if isinstance(version, dict) else None
                )
                entry["author_account_id"] = (
                    str(entry["author_account_id"])
                    if entry["author_account_id"]
                    else None
                )
                profile = author_profile(entry["author_account_id"])
                if profile:
                    entry["author_display_name"] = _profile_value(
                        profile, "displayName"
                    ) or _profile_value(profile, "publicName")
                    entry["author_email"] = _profile_value(profile, "email")
            entry["updated_at"] = get_updated_at(detail)
            document = extract_item_document(detail)
            if not document.text.strip():
                detail = api.get_page_detail(page_id, "atlas_doc_format")
                document = extract_item_document(detail)
            if not document.text.strip():
                raise EvaluationError(
                    "La página no contiene cuerpo legible en storage o Atlas Doc Format."
                )
            entry["document"] = document
            entry["comments"] = api.get_page_comments(page_id)
            entry["likes_count"] = api.get_likes_count(page_id)
            spelling_source = f"{entry['title']} {document.spelling_text}"
            word_count, spelling_errors = spelling_counts(spelling_source, spell_checker)
            entry["word_count"] = word_count
            entry["spelling_errors_count"] = spelling_errors
            link_urls = normalize_web_links(document.links, entry["page_url"])
            valid, invalid, unchecked = link_checker(link_urls)
            entry["valid_links_count"] = valid
            entry["invalid_links_count"] = invalid
            entry["unchecked_links_count"] = unchecked
        except Exception as error:
            entry["failure"] = f"{error.__class__.__name__}: {error}"[:2000]
        work.append(entry)
    return work


async def analyze_pages(
    pages: list[dict[str, Any]],
    token: str,
    model: str,
    evaluator_factory: CopilotFactory = CopilotEvaluator,
) -> None:
    async with evaluator_factory(token, model) as evaluator:
        for page in pages:
            if page["failure"]:
                continue
            try:
                page["analysis"] = await evaluator.analyze_structure(page)
                classifications = await evaluator.classify_comments(
                    page["title"], page["comments"]
                )
                page["comment_metrics"] = comment_metrics(
                    classifications
                )
            except Exception as error:
                page["failure"] = f"{error.__class__.__name__}: {error}"[:2000]


class EvaluationService:
    def __init__(
        self,
        settings: Settings,
        confluence_factory: ConfluenceFactory = ConfluenceClient,
        evaluator_factory: CopilotFactory = CopilotEvaluator,
        repository_factory: RepositoryFactory = EvaluationDatabase,
        spell_checker_factory: Callable[[], SpellChecker] = create_spell_checker,
        link_checker: LinkChecker = check_links,
    ) -> None:
        self.settings = settings
        self.confluence_factory = confluence_factory
        self.evaluator_factory = evaluator_factory
        self.repository_factory = repository_factory
        self.spell_checker_factory = spell_checker_factory
        self.link_checker = link_checker

    def run(self) -> int:
        api = self.confluence_factory(self.settings)
        try:
            spaces = api.get_spaces()
            spaces_by_id = {
                str(space["id"]): space for space in spaces if "id" in space
            }
            pages = api.get_pages()
            print(
                f"Confluence: {len(spaces_by_id)} espacios visibles, "
                f"{len(pages)} páginas actuales."
            )

            work = collect_page_work(
                api,
                pages,
                spaces_by_id,
                self.spell_checker_factory(),
                self.link_checker,
            )
            asyncio.run(
                analyze_pages(
                    work,
                    self.settings.copilot_token,
                    self.settings.copilot_model,
                    self.evaluator_factory,
                )
            )
            prepare_scores(work, datetime.now(UTC))

            failures = self._report_results(work)
            if self.settings.dry_run:
                print("Dry-run completado; no se escribieron resultados en PostgreSQL.")
            else:
                self._persist(spaces, work)
            return 1 if failures else 0
        finally:
            api.close()

    def _report_results(self, pages: list[dict[str, Any]]) -> int:
        failures = 0
        for page in pages:
            if page["failure"]:
                failures += 1
                print(
                    f"Evaluación fallida: [{page['space_key']}] "
                    f"{page['title']}: {page['failure']}"
                )
            else:
                print(
                    f"Evaluada: [{page['space_key']}] {page['title']} "
                    f"({page['total_score']:.2f}/100)"
                )
        return failures

    def _persist(
        self, spaces: list[dict[str, Any]], pages: list[dict[str, Any]]
    ) -> None:
        database = self.repository_factory(self.settings.database_url)
        try:
            database.persist(
                spaces,
                pages,
                self.settings.evaluation_date,
                self.settings.copilot_model,
            )
        finally:
            database.close()
        print(
            f"Persistidas {len(pages)} evaluaciones para "
            f"{self.settings.evaluation_date}."
        )


def run_evaluation(settings: Settings) -> int:
    return EvaluationService(settings).run()
