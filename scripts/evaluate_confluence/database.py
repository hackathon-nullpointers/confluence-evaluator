"""PostgreSQL persistence for spaces, pages, and daily evaluations."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import psycopg

from .config import EvaluationError
from .constants import PROMPT_VERSION, SCORING_VERSION
from .scoring import weighted_total


class EvaluationDatabase:
    def __init__(self, database_url: str) -> None:
        self.connection = psycopg.connect(database_url, connect_timeout=15)

    def close(self) -> None:
        self.connection.close()

    def persist(
        self,
        spaces: list[dict[str, Any]],
        pages: list[dict[str, Any]],
        evaluation_date: date,
        model: str,
    ) -> None:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                space_ids: dict[str, int] = {}
                for space in spaces:
                    external_id = str(space["id"])
                    cursor.execute(
                        """
                        INSERT INTO confluence_spaces
                            (confluence_space_id, space_key, name, confluence_status)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (confluence_space_id) DO UPDATE SET
                            space_key = EXCLUDED.space_key,
                            name = EXCLUDED.name,
                            confluence_status = EXCLUDED.confluence_status
                        RETURNING id
                        """,
                        (
                            external_id,
                            space["key"],
                            space["name"],
                            space.get("status", "current"),
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise EvaluationError(f"No se guardó el espacio {space['key']}.")
                    space_ids[external_id] = row[0]

                page_ids: dict[str, int] = {}
                for page in pages:
                    cursor.execute(
                        """
                        INSERT INTO confluence_pages
                            (confluence_page_id, space_id, title, page_url, confluence_status)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (confluence_page_id) DO UPDATE SET
                            space_id = EXCLUDED.space_id,
                            title = EXCLUDED.title,
                            page_url = EXCLUDED.page_url,
                            confluence_status = EXCLUDED.confluence_status
                        RETURNING id
                        """,
                        (
                            page["page_id"],
                            space_ids[page["space_id"]],
                            page["title"],
                            page["page_url"],
                            page["confluence_status"],
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise EvaluationError(f"No se guardó la página {page['page_id']}.")
                    page_ids[page["page_id"]] = row[0]

                evaluation_columns = [
                    "page_id",
                    "evaluation_date",
                    "evaluated_at",
                    "author_account_id",
                    "author_exists",
                    "comments_analyzed_count",
                    "positive_comments_count",
                    "neutral_comments_count",
                    "negative_comments_count",
                    "positive_comment_relevance",
                    "negative_comment_relevance",
                    "confluence_updated_at",
                    "likes_count",
                    "word_count",
                    "spelling_errors_count",
                    "valid_links_count",
                    "invalid_links_count",
                    "unchecked_links_count",
                    "comparison_group",
                    "author_exists_score",
                    "comments_score",
                    "freshness_score",
                    "structure_score",
                    "likes_score",
                    "spelling_score",
                    "links_score",
                    "evaluation_status",
                    "error_message",
                    "ai_model",
                    "ai_prompt_version",
                    "scoring_version",
                    "total_score",
                ]
                placeholders = ", ".join(["%s"] * len(evaluation_columns))
                updates = ", ".join(
                    f"{column} = EXCLUDED.{column}"
                    for column in evaluation_columns
                    if column not in {"page_id", "evaluation_date"}
                )
                insert_evaluation = f"""
                    INSERT INTO page_evaluations ({", ".join(evaluation_columns)})
                    VALUES ({placeholders})
                    ON CONFLICT (page_id, evaluation_date) DO UPDATE SET {updates}
                """

                now = datetime.now(UTC)
                for page in pages:
                    succeeded = not page["failure"]
                    comments = page.get("comment_metrics", {})
                    scores = page.get("scores", {})
                    total = weighted_total(scores) if succeeded else None
                    values = {
                        "page_id": page_ids[page["page_id"]],
                        "evaluation_date": evaluation_date,
                        "evaluated_at": now,
                        "author_account_id": page["author_account_id"],
                        "author_exists": bool(page["author_account_id"]),
                        "comments_analyzed_count": comments.get(
                            "comments_analyzed_count"
                        ),
                        "positive_comments_count": comments.get(
                            "positive_comments_count"
                        ),
                        "neutral_comments_count": comments.get("neutral_comments_count"),
                        "negative_comments_count": comments.get(
                            "negative_comments_count"
                        ),
                        "positive_comment_relevance": comments.get(
                            "positive_comment_relevance"
                        ),
                        "negative_comment_relevance": comments.get(
                            "negative_comment_relevance"
                        ),
                        "confluence_updated_at": page["updated_at"],
                        "likes_count": page["likes_count"],
                        "word_count": page["word_count"],
                        "spelling_errors_count": page["spelling_errors_count"],
                        "valid_links_count": page["valid_links_count"],
                        "invalid_links_count": page["invalid_links_count"],
                        "unchecked_links_count": page["unchecked_links_count"],
                        "comparison_group": page.get("comparison_group"),
                        "author_exists_score": scores.get("author_exists_score"),
                        "comments_score": scores.get("comments_score"),
                        "freshness_score": scores.get("freshness_score"),
                        "structure_score": scores.get("structure_score"),
                        "likes_score": scores.get("likes_score"),
                        "spelling_score": scores.get("spelling_score"),
                        "links_score": scores.get("links_score"),
                        "evaluation_status": "completed" if succeeded else "failed",
                        "error_message": page["failure"],
                        "ai_model": model,
                        "ai_prompt_version": PROMPT_VERSION,
                        "scoring_version": SCORING_VERSION,
                        "total_score": total,
                    }
                    cursor.execute(
                        insert_evaluation,
                        tuple(values[column] for column in evaluation_columns),
                    )
