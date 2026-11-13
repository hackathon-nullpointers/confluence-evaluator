"""Confluence Cloud REST API client."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import EvaluationError, Settings
from .documents import extract_item_document


class ConfluenceClient:
    def __init__(self, settings: Settings) -> None:
        self.site_url = settings.site_url
        self.api_root = f"{settings.site_url}/wiki/api/v2"
        self.hostname = urlsplit(settings.site_url).hostname
        self.session = requests.Session()
        self._user_cache: dict[str, dict[str, Any] | None] = {}
        self.session.auth = (settings.atlassian_email, settings.atlassian_token)
        self._last_link_header = ""
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "confluence-evaluator/1.0",
            }
        )
        retry = Retry(
            total=4,
            connect=3,
            read=2,
            status=3,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def close(self) -> None:
        self.session.close()

    def _validate_api_url(self, url: str) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != self.hostname
            or not parsed.path.startswith(("/wiki/api/v2/", "/wiki/rest/api/"))
        ):
            raise EvaluationError("Confluence devolvió una URL de API no confiable.")

    def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> Any:
        self._validate_api_url(url)
        try:
            response = self.session.get(
                url, params=params, timeout=(10, 60), allow_redirects=False
            )
            if allow_not_found and response.status_code == 404:
                return None
            response.raise_for_status()
            self._last_link_header = response.headers.get("Link", "")
            return response.json()
        except requests.RequestException as error:
            raise EvaluationError(
                f"Falló GET {urlsplit(url).path}: {error.__class__.__name__}"
            ) from error
        except ValueError as error:
            raise EvaluationError(
                f"Confluence devolvió JSON inválido para {urlsplit(url).path}."
            ) from error

    def get_all(
        self, path: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        url = f"{self.api_root}/{path.lstrip('/')}"
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        next_params = params
        while url:
            if url in seen:
                raise EvaluationError("La paginación de Confluence repitió una URL.")
            seen.add(url)
            payload = self.get_json(url, params=next_params)
            next_params = None
            if not isinstance(payload, dict):
                raise EvaluationError("La API devolvió un formato de colección inesperado.")
            batch = payload.get("results", [])
            if not isinstance(batch, list):
                raise EvaluationError("La API devolvió resultados de página inválidos.")
            results.extend(item for item in batch if isinstance(item, dict))
            next_url = payload.get("_links", {}).get("next")
            if not next_url:
                next_url = self._next_link_from_header(url)
            url = urljoin(url, next_url) if next_url else ""
        return results

    def _next_link_from_header(self, current_url: str) -> str | None:
        for item in self._last_link_header.split(","):
            if 'rel="next"' in item:
                match = re.search(r"<([^>]+)>", item)
                if match:
                    return urljoin(current_url, match.group(1))
        return None

    def get_spaces(self) -> list[dict[str, Any]]:
        return self.get_all("/spaces", {"limit": 100})

    def get_pages(self) -> list[dict[str, Any]]:
        return self.get_all(
            "/pages",
            {"status": "current", "body-format": "storage", "limit": 100},
        )

    def get_user(self, account_id: str) -> dict[str, Any] | None:
        if account_id not in self._user_cache:
            payload = self.get_json(
                f"{self.site_url}/wiki/rest/api/user",
                {"accountId": account_id},
                allow_not_found=True,
            )
            if payload is not None and not isinstance(payload, dict):
                raise EvaluationError("Confluence devolvió un perfil de usuario inválido.")
            self._user_cache[account_id] = payload
        return self._user_cache[account_id]

    def get_page_detail(
        self, page_id: str, body_format: str = "storage"
    ) -> dict[str, Any]:
        url = f"{self.api_root}/pages/{quote(page_id, safe='')}"
        payload = self.get_json(url, {"body-format": body_format})
        if not isinstance(payload, dict):
            raise EvaluationError(f"Detalle de página {page_id} con formato inválido.")
        return payload

    def get_page_comments(self, page_id: str) -> list[str]:
        comments: list[str] = []
        visited: set[tuple[str, str]] = set()
        for kind in ("footer-comments", "inline-comments"):
            roots = self.get_all(
                f"/pages/{quote(page_id, safe='')}/{kind}",
                {"status": "current", "body-format": "storage", "limit": 100},
            )
            for comment in roots:
                self._collect_comment_tree(kind, comment, comments, visited)
        return comments

    def _collect_comment_tree(
        self,
        kind: str,
        comment: dict[str, Any],
        comments: list[str],
        visited: set[tuple[str, str]],
    ) -> None:
        comment_id = str(comment.get("id", ""))
        if comment_id and (kind, comment_id) in visited:
            return
        if comment_id:
            visited.add((kind, comment_id))
        text = extract_item_document(comment).text
        if text:
            comments.append(text)
        if not comment_id:
            return
        children = self.get_all(
            f"/{kind}/{quote(comment_id, safe='')}/children",
            {"body-format": "storage", "limit": 100},
        )
        for child in children:
            self._collect_comment_tree(kind, child, comments, visited)

    def get_likes_count(self, page_id: str) -> int:
        url = f"{self.api_root}/pages/{quote(page_id, safe='')}/likes/count"
        payload = self.get_json(url)
        if isinstance(payload, int) and not isinstance(payload, bool):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("count"), int):
            return payload["count"]
        raise EvaluationError(f"Confluence devolvió un conteo de likes inválido para {page_id}.")

    def page_url(self, page: dict[str, Any]) -> str:
        webui = page.get("_links", {}).get("webui")
        if isinstance(webui, str) and webui:
            if webui.startswith("/spaces/"):
                webui = f"/wiki{webui}"
            return urljoin(self.site_url, webui)
        return f"{self.site_url}/wiki/pages/viewpage.action?pageId={quote(str(page['id']))}"
