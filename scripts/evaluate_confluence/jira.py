"""Create and update Jira issues for low-scoring Confluence pages."""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import quote

import requests

from .config import EvaluationError, Settings
from .constants import WEIGHTS
from .ports import JiraIssueResult

SCORE_LABELS = {
    "author_exists_score": "Autor identificado",
    "comments_score": "Comentarios",
    "freshness_score": "Vigencia",
    "structure_score": "Estructura",
    "likes_score": "Likes",
    "spelling_score": "Ortografía",
    "links_score": "Enlaces",
}


class JiraClient:
    def __init__(self, settings: Settings) -> None:
        self.site_url = settings.site_url
        self.email = settings.atlassian_email
        self.token = settings.atlassian_token
        self.project_key = settings.jira_project_key
        self.session = requests.Session()
        self.session.auth = (self.email, self.token)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "confluence-evaluator/1.0",
            }
        )

    def close(self) -> None:
        self.session.close()

    def _request_json(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            response = self.session.request(
                method,
                f"{self.site_url}/rest/api/3/{path.lstrip('/')}",
                json=payload,
                timeout=(10, 60),
            )
            response.raise_for_status()
        except requests.HTTPError as error:
            status = error.response.status_code if error.response else "desconocido"
            raise EvaluationError(
                f"Jira devolvió HTTP {status} para {method} {path}."
            ) from error
        except requests.RequestException as error:
            raise EvaluationError(
                f"Falló la solicitud a Jira: {error.__class__.__name__}."
            ) from error

        if response.status_code == 204:
            return {}
        try:
            result = response.json()
        except ValueError as error:
            raise EvaluationError("Jira devolvió JSON inválido.") from error
        if not isinstance(result, dict):
            raise EvaluationError("Jira devolvió una respuesta con formato inválido.")
        return result

    @staticmethod
    def _evaluation_label(page_id: str, evaluation_date: date) -> str:
        safe_page_id = re.sub(r"[^A-Za-z0-9_-]", "-", page_id)
        return f"confluence-eval-{safe_page_id}-{evaluation_date:%Y%m%d}"

    @staticmethod
    def _paragraph(text: str) -> dict[str, Any]:
        return {
            "type": "paragraph",
            "content": [{"type": "text", "text": text}],
        }

    @classmethod
    def _section(
        cls,
        title: str,
        paragraphs: list[str] | None = None,
        bullets: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": title}],
            }
        ]
        nodes.extend(cls._paragraph(item) for item in paragraphs or [])
        if bullets:
            nodes.append(
                {
                    "type": "bulletList",
                    "content": [
                        {"type": "listItem", "content": [cls._paragraph(item)]}
                        for item in bullets
                    ],
                }
            )
        return nodes

    @classmethod
    def _description(cls, page: dict[str, Any]) -> dict[str, Any]:
        score_lines = [
            f"{SCORE_LABELS[criterion]}: {page['scores'][criterion]:.2f}/100 "
            f"(peso {weight} %)"
            for criterion, weight in WEIGHTS.items()
        ]
        feedback = page["evaluation_feedback"]
        content = [
            cls._paragraph(f"Página Confluence: {page['page_url']}"),
            *cls._section(
                "Resultado",
                paragraphs=[
                    f"Puntaje total: {page['total_score']:.2f}/100.",
                    feedback["evaluation_reason"],
                ],
            ),
            *cls._section("Desglose de puntajes", bullets=score_lines),
            *cls._section("Hallazgos (insights)", bullets=feedback["insights"]),
            *cls._section("Recomendaciones", bullets=feedback["recommendations"]),
        ]
        return {"type": "doc", "version": 1, "content": content}

    def _find_issue(self, label: str) -> str | None:
        jql = f'project = "{self.project_key}" AND labels = "{label}"'
        response = self._request_json(
            "POST",
            "search/jql",
            {"jql": jql, "fields": ["key"], "maxResults": 2},
        )
        issues = response.get("issues")
        if not isinstance(issues, list):
            raise EvaluationError("Jira devolvió resultados de búsqueda inválidos.")
        if len(issues) > 1:
            raise EvaluationError(
                f"Hay varios tickets Jira para la evaluación identificada por {label}."
            )
        if not issues:
            return None
        issue = issues[0]
        key = issue.get("key") if isinstance(issue, dict) else None
        if not isinstance(key, str) or not key:
            raise EvaluationError("Jira devolvió un ticket sin clave válida.")
        return key

    def upsert_evaluation_issue(
        self, page: dict[str, Any], evaluation_date: date
    ) -> JiraIssueResult:
        label = self._evaluation_label(page["page_id"], evaluation_date)
        score = page["total_score"]
        prefix = "[Confluence] "
        suffix = f" - Puntaje {score:.2f}/100"
        title_limit = 255 - len(prefix) - len(suffix)
        summary = f"{prefix}{page['title'][:title_limit]}{suffix}"
        description = self._description(page)
        existing_key = self._find_issue(label)
        if existing_key:
            self._request_json(
                "PUT",
                f"issue/{quote(existing_key, safe='')}",
                {"fields": {"summary": summary, "description": description}},
            )
            return JiraIssueResult(
                existing_key,
                f"{self.site_url}/browse/{quote(existing_key, safe='')}",
                "updated",
            )

        response = self._request_json(
            "POST",
            "issue",
            {
                "fields": {
                    "project": {"key": self.project_key},
                    "issuetype": {"name": "Task"},
                    "summary": summary,
                    "description": description,
                    "labels": [label],
                }
            },
        )
        issue_key = response.get("key")
        if not isinstance(issue_key, str) or not issue_key:
            raise EvaluationError("Jira creó el ticket sin devolver su clave.")
        return JiraIssueResult(
            issue_key,
            f"{self.site_url}/browse/{quote(issue_key, safe='')}",
            "created",
        )
