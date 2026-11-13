#!/usr/bin/env python3
"""Create the mock spaces and pages in a Confluence Cloud site."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SPACE_DATA = ROOT / "mock-data" / "spaces.json"
PAGE_DATA = ROOT / "mock-data" / "pages.json"
DEFAULT_SITE_URL = "https://bcphackaton.atlassian.net"
TIMEOUT_SECONDS = 30


class ConfluenceError(RuntimeError):
    """Raised when a Confluence request or response is unsuccessful."""


def load_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise ConfluenceError(f"No se pudo leer {path}: {error}") from error


def normalize_site_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ConfluenceError("CONFLUENCE_BASE_URL debe ser una URL HTTPS válida.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfluenceError(
            "CONFLUENCE_BASE_URL no debe incluir credenciales, query ni fragmento."
        )

    path = parsed.path.rstrip("/")
    if path.endswith("/wiki/home"):
        path = path[: -len("/wiki/home")]
    elif path.endswith("/wiki"):
        path = path[: -len("/wiki")]
    if path:
        raise ConfluenceError(
            "CONFLUENCE_BASE_URL debe ser el dominio del sitio o terminar en /wiki/home."
        )
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


class ConfluenceClient:
    def __init__(self, site_url: str, email: str, api_token: str) -> None:
        self.site_url = normalize_site_url(site_url)
        self.api_root = f"{self.site_url}/wiki/api/v2"
        self.hostname = urlsplit(self.site_url).hostname
        token = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
        self.authorization = f"Basic {token}"

    def request(self, method: str, url: str, body: dict | None = None) -> tuple[dict, dict]:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != self.hostname
            or not parsed.path.startswith("/wiki/api/v2/")
        ):
            raise ConfluenceError("Se rechazó una URL de API fuera del sitio configurado.")

        headers = {
            "Accept": "application/json",
            "Authorization": self.authorization,
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                response_body = response.read()
                result = json.loads(response_body) if response_body else {}
                return result, dict(response.headers.items())
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise ConfluenceError(
                f"Confluence respondió HTTP {error.code} para {method} "
                f"{parsed.path}: {details or error.reason}"
            ) from error
        except URLError as error:
            raise ConfluenceError(
                f"No se pudo conectar con Confluence: {error.reason}"
            ) from error
        except json.JSONDecodeError as error:
            raise ConfluenceError(
                f"Confluence devolvió una respuesta JSON inválida para {parsed.path}."
            ) from error

    def get_all(self, path: str) -> list[dict]:
        url = f"{self.api_root}{path}"
        results: list[dict] = []
        seen_urls: set[str] = set()
        while url:
            if url in seen_urls:
                raise ConfluenceError("La paginación de Confluence repitió una URL.")
            seen_urls.add(url)
            page, headers = self.request("GET", url)
            results.extend(page.get("results", []))
            url = self.next_url(url, page, headers)
        return results

    @staticmethod
    def next_url(current_url: str, body: dict, headers: dict) -> str | None:
        next_link = body.get("_links", {}).get("next")
        if next_link:
            return urljoin(current_url, next_link)

        link_header = next(
            (value for key, value in headers.items() if key.lower() == "link"),
            "",
        )
        for item in link_header.split(","):
            if 'rel="next"' in item:
                match = re.search(r"<([^>]+)>", item)
                if match:
                    return urljoin(current_url, match.group(1))
        return None

    def find_space(self, key: str) -> dict | None:
        spaces = self.get_all(f"/spaces?keys={quote(key)}&limit=100")
        return next((space for space in spaces if space.get("key") == key), None)

    def create_space(self, space: dict) -> dict:
        description = space.get("description", "")
        payload = {
            "key": space["key"],
            "name": space["name"],
            "description": {
                "representation": "plain",
                "value": description,
            },
        }
        created, _ = self.request("POST", f"{self.api_root}/spaces", payload)
        return created

    def page_exists(self, space_id: str, title: str) -> bool:
        query = (
            f"/pages?space-id={quote(str(space_id))}"
            f"&title={quote(title)}&status=current&limit=100"
        )
        pages = self.get_all(query)
        return any(page.get("title") == title for page in pages)

    def create_page(self, space_id: str, payload: dict) -> dict:
        page_payload = dict(payload)
        page_payload["spaceId"] = str(space_id)
        created, _ = self.request("POST", f"{self.api_root}/pages", page_payload)
        return created


def load_credentials() -> tuple[str, str, str]:
    site_url = os.environ.get("CONFLUENCE_BASE_URL", DEFAULT_SITE_URL)
    email = os.environ.get("ATLASSIAN_EMAIL")
    api_token = os.environ.get("ATLASSIAN_API_TOKEN")
    if not email or not api_token:
        raise ConfluenceError(
            "Configura ATLASSIAN_EMAIL y ATLASSIAN_API_TOKEN en tu entorno. "
            "No guardes el token en el repositorio."
        )
    return site_url, email, api_token


def run(apply_changes: bool) -> int:
    spaces_data = load_json(SPACE_DATA)
    pages_data = load_json(PAGE_DATA)
    site_url, email, api_token = load_credentials()
    client = ConfluenceClient(site_url, email, api_token)

    spaces_by_key: dict[str, dict] = {}
    for space in spaces_data["spaces"]:
        existing = client.find_space(space["key"])
        if existing:
            if existing.get("name") != space["name"]:
                raise ConfluenceError(
                    f"La clave {space['key']} ya pertenece al espacio "
                    f"{existing.get('name')!r}, no a {space['name']!r}."
                )
            spaces_by_key[space["key"]] = existing
            print(f"Espacio existente: {space['key']} — {space['name']}")
        elif apply_changes:
            created = client.create_space(space)
            spaces_by_key[space["key"]] = created
            print(f"Espacio creado: {space['key']} — {space['name']}")
        else:
            print(f"Se crearía el espacio: {space['key']} — {space['name']}")

    created_count = 0
    skipped_count = 0
    for page in pages_data["pages"]:
        space_key = page["spaceKey"]
        space = spaces_by_key.get(space_key)
        if not space:
            print(f"Se crearía la página en {space_key}: {page['payload']['title']}")
            continue

        title = page["payload"]["title"]
        if client.page_exists(space["id"], title):
            skipped_count += 1
            print(f"Se omite página existente: [{space_key}] {title}")
            continue

        if apply_changes:
            result = client.create_page(space["id"], page["payload"])
            created_count += 1
            print(f"Página creada: [{space_key}] {title} (id={result.get('id', 'n/a')})")
        else:
            print(f"Se crearía la página: [{space_key}] {title}")

    if apply_changes:
        print(f"Finalizado: {created_count} páginas creadas, {skipped_count} omitidas.")
    else:
        print("Dry-run completado: no se creó ni modificó contenido.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Crea los espacios y páginas definidos en mock-data. "
            "Por defecto consulta y muestra el plan sin escribir."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="crear espacios y páginas; sin esta opción solo se ejecuta dry-run",
    )
    args = parser.parse_args()
    try:
        return run(apply_changes=args.apply)
    except ConfluenceError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
