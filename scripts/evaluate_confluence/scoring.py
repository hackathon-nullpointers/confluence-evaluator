"""Pure scoring rules and spelling measurements."""

from __future__ import annotations

import calendar
import os
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from spellchecker import SpellChecker

from .config import EvaluationError
from .constants import DEFAULT_SPELLING_ALLOWLIST, MIN_PEER_GROUP_SIZE, WEIGHTS


def get_updated_at(page: dict[str, Any]) -> datetime:
    version = page.get("version")
    timestamp = version.get("createdAt") if isinstance(version, dict) else None
    if not isinstance(timestamp, str) or not timestamp:
        timestamp = page.get("updatedAt")
    if not isinstance(timestamp, str) or not timestamp:
        raise EvaluationError("La respuesta de Confluence no incluye fecha de actualización.")
    try:
        result = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvaluationError("Confluence devolvió una fecha de actualización inválida.") from error
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)

def subtract_calendar_months(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 - months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)

def freshness_score(updated_at: datetime, as_of: datetime) -> int:
    updated = updated_at.astimezone(UTC) if updated_at.tzinfo else updated_at.replace(tzinfo=UTC)
    current = as_of.astimezone(UTC) if as_of.tzinfo else as_of.replace(tzinfo=UTC)
    if updated > subtract_calendar_months(current, 3):
        return 100
    if updated > subtract_calendar_months(current, 6):
        return 75
    if updated > subtract_calendar_months(current, 12):
        return 50
    if updated > subtract_calendar_months(current, 24):
        return 25
    return 0

def spelling_counts(text: str, spell_checker: SpellChecker) -> tuple[int, int]:
    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", text)
    normalized = [word.lower() for word in words if len(word) > 1]
    unknown = spell_checker.unknown(normalized)
    errors = sum(word in unknown for word in normalized)
    return len(normalized), errors

def spelling_score(word_count: int, error_count: int) -> float:
    if word_count <= 0:
        return 100.0
    return max(0.0, 100.0 * (1.0 - error_count / word_count))

def comment_score(positive_relevance: float, negative_relevance: float) -> float:
    total = positive_relevance + negative_relevance
    if total <= 0:
        return 50.0
    return 100.0 * positive_relevance / total

def links_score(valid_count: int, invalid_count: int, unchecked_count: int) -> float:
    checked = valid_count + invalid_count
    if checked:
        return 100.0 * valid_count / checked
    return 100.0 if unchecked_count == 0 else 50.0

def comment_metrics(classifications: dict[int, tuple[str, float]]) -> dict[str, Any]:
    counts = Counter(sentiment for sentiment, _ in classifications.values())
    positive_relevance = sum(
        relevance
        for sentiment, relevance in classifications.values()
        if sentiment == "positive"
    )
    negative_relevance = sum(
        relevance
        for sentiment, relevance in classifications.values()
        if sentiment == "negative"
    )
    return {
        "comments_analyzed_count": len(classifications),
        "positive_comments_count": counts["positive"],
        "neutral_comments_count": counts["neutral"],
        "negative_comments_count": counts["negative"],
        "positive_comment_relevance": round(positive_relevance, 4),
        "negative_comment_relevance": round(negative_relevance, 4),
        "comments_score": comment_score(positive_relevance, negative_relevance),
    }

def assign_comparison_groups(
    pages: list[dict[str, Any]], min_group_size: int = MIN_PEER_GROUP_SIZE
) -> None:
    exact_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    type_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page in pages:
        analysis = page["analysis"]
        exact_groups[(analysis["domain"], analysis["document_type"])].append(page)
        type_groups[analysis["document_type"]].append(page)

    for page in pages:
        analysis = page["analysis"]
        exact_key = (analysis["domain"], analysis["document_type"])
        if len(exact_groups[exact_key]) >= min_group_size:
            page["comparison_group"] = f"{exact_key[0]}:{exact_key[1]}"
        elif len(type_groups[analysis["document_type"]]) >= min_group_size:
            page["comparison_group"] = f"type:{analysis['document_type']}"
        else:
            page["comparison_group"] = "global"

def percentile_likes_scores(pages: list[dict[str, Any]]) -> None:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page in pages:
        groups[page["comparison_group"]].append(page)

    for group in groups.values():
        likes = [page["likes_count"] for page in group]
        for page in group:
            below = sum(value < page["likes_count"] for value in likes)
            tied = sum(value == page["likes_count"] for value in likes)
            if len(group) < 2:
                score = 50.0
            else:
                average_zero_based_rank = below + (tied - 1) / 2
                score = 100.0 * average_zero_based_rank / (len(group) - 1)
            scores = page.get("scores")
            if not isinstance(scores, dict):
                scores = {}
                page["scores"] = scores
            scores["likes_score"] = score

def weighted_total(scores: dict[str, float]) -> float:
    missing = set(WEIGHTS) - scores.keys()
    if missing:
        raise EvaluationError("Faltan puntajes para: " + ", ".join(sorted(missing)))
    if any(not 0 <= scores[name] <= 100 for name in WEIGHTS):
        raise EvaluationError("Todos los puntajes deben estar entre 0 y 100.")
    return round(sum(scores[name] * weight for name, weight in WEIGHTS.items()) / 100, 2)

def create_spell_checker() -> SpellChecker:
    checker = SpellChecker(language="es")
    extra_words = {
        word.strip()
        for word in os.environ.get("SPELLING_ALLOWLIST", "").split(",")
        if word.strip()
    }
    checker.word_frequency.load_words(DEFAULT_SPELLING_ALLOWLIST | extra_words)
    return checker

def score_page(page: dict[str, Any], as_of: datetime) -> dict[str, float]:
    updated_at = page["updated_at"]
    if not isinstance(updated_at, datetime):
        raise EvaluationError("No hay fecha de actualización para puntuar la página.")
    comment_values = page["comment_metrics"]
    structure_score = page["analysis"]["structure_score"]
    word_count = page["word_count"]
    spelling_errors = page["spelling_errors_count"]
    valid_links = page["valid_links_count"]
    invalid_links = page["invalid_links_count"]
    unchecked_links = page["unchecked_links_count"]
    scores = {
        "author_exists_score": 100.0 if page["author_account_id"] else 0.0,
        "comments_score": comment_values["comments_score"],
        "freshness_score": float(freshness_score(updated_at, as_of)),
        "structure_score": float(structure_score),
        "spelling_score": spelling_score(word_count, spelling_errors),
        "links_score": links_score(valid_links, invalid_links, unchecked_links),
    }
    if not isinstance(page.get("scores"), dict):
        page["scores"] = {}
    page["scores"].update(scores)
    return page["scores"]

def prepare_scores(pages: list[dict[str, Any]], as_of: datetime) -> None:
    successful = [page for page in pages if not page["failure"]]
    assign_comparison_groups(successful)
    percentile_likes_scores(successful)
    for page in successful:
        scores = score_page(page, as_of)
        page["total_score"] = weighted_total(scores)
