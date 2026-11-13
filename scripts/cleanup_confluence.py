"""Delete tracked pages and project issues, then empty evaluator tables."""

from __future__ import annotations

import argparse
import os
import re
import sys
from urllib.parse import quote

import psycopg
import requests

from scripts.evaluate_confluence.config import EvaluationError, normalize_site_url


TABLES = (
    "jira_evaluation_issues",
    "page_evaluations",
    "confluence_pages",
    "confluence_spaces",
)


class CleanupClient:
    def __init__(self, site: str, email: str, token: str) -> None:
        self.site = site
        self.session = requests.Session()
        self.session.auth = (email, token)
        self.session.headers.update({"Accept": "application/json"})

    def request(self, method: str, path: str, **kwargs: object) -> dict:
        try:
            response = self.session.request(
                method, self.site + path, timeout=(10, 60),
                allow_redirects=False, **kwargs,
            )
        except requests.RequestException as error:
            raise EvaluationError(
                f"Falló {method} {path}: {error.__class__.__name__}."
            ) from error
        with response:
            if not 200 <= response.status_code < 300:
                raise EvaluationError(
                    f"{method} {path}: HTTP {response.status_code}. "
                    "Se detiene la limpieza; la base no se vaciará."
                )
            if response.status_code == 204:
                return {}
            try:
                data = response.json()
            except ValueError as error:
                raise EvaluationError(f"JSON inválido para {method} {path}.") from error
            if not isinstance(data, dict):
                raise EvaluationError(f"Respuesta inválida para {method} {path}.")
            return data

    def list_issues(self, project: str) -> list[str]:
        keys: list[str] = []
        seen_tokens: set[str] = set()
        token = None
        while True:
            payload: dict = {
                "jql": f'project = "{project}" ORDER BY key ASC',
                "fields": ["key"],
                "maxResults": 100,
            }
            if token:
                payload["nextPageToken"] = token
            data = self.request("POST", "/rest/api/3/search/jql", json=payload)
            issues = data.get("issues")
            if not isinstance(issues, list):
                raise EvaluationError("Jira devolvió una lista de issues inválida.")
            for issue in issues:
                key = issue.get("key") if isinstance(issue, dict) else None
                if not isinstance(key, str) or not key.startswith(project + "-"):
                    raise EvaluationError("Jira devolvió un issue fuera del proyecto.")
                if key in keys:
                    raise EvaluationError("Jira repitió un issue durante la paginación.")
                keys.append(key)
            token = data.get("nextPageToken")
            if not token:
                if data.get("isLast") is not True:
                    raise EvaluationError("Jira no confirmó el fin de la paginación.")
                return keys
            if not isinstance(token, str) or token in seen_tokens:
                raise EvaluationError("Token de paginación Jira inválido o repetido.")
            seen_tokens.add(token)


def cleanup(connection: psycopg.Connection, client: CleanupClient,
            project: str | None, apply: bool, confirmation: str | None) -> None:
    # Keep snapshots stable; do not hold this transaction during remote requests.
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT confluence_page_id, title FROM public.confluence_pages "
                "ORDER BY id"
            )
            pages = cursor.fetchall()
            if project is None:
                cursor.execute(
                    "SELECT DISTINCT jira_project_key FROM public.jira_evaluation_issues "
                    "ORDER BY jira_project_key"
                )
                projects = [row[0] for row in cursor.fetchall()]
            else:
                projects = [project]
    for key in projects:
        if not isinstance(key, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise EvaluationError("Clave de proyecto Jira inválida en el inventario.")
    issues = [issue for key in projects for issue in client.list_issues(key)]
    print(f"Sitio: {client.site}; proyectos Jira: {', '.join(projects) or '(ninguno)'}")
    print(f"Páginas registradas: {len(pages)}; tickets visibles: {len(issues)}.")
    for page_id, title in pages:
        print(f"Página a eliminar: {page_id} - {title}")
    for key in issues:
        print(f"Ticket a eliminar: {key}")
    print("Espacios Confluence: se conservan.")
    print("Tablas a vaciar: " + ", ".join(TABLES))
    scope = project if project is not None else "PROYECTOS-BD:" + ",".join(projects)
    expected = f"BORRAR {client.site} {scope}"
    if not apply:
        print(f"Simulación: sin cambios. Confirmación requerida: {expected!r}")
        return
    if confirmation != expected:
        raise EvaluationError(f"Para aplicar, --confirm debe ser exactamente {expected!r}.")

    for page_id, _ in pages:
        client.request("DELETE", f"/wiki/api/v2/pages/{quote(str(page_id), safe='')}")
        print(f"Página eliminada: {page_id}")
    # Delete subtasks first so parent deletion never silently removes unseen issues.
    while issues:
        progress = False
        remaining = []
        for key in issues:
            detail = client.request(
                "GET", f"/rest/api/3/issue/{quote(key, safe='')}",
                params={"fields": "subtasks"},
            )
            subtasks = detail.get("fields", {}).get("subtasks")
            if not isinstance(subtasks, list):
                raise EvaluationError(f"No se pudieron consultar subtareas de {key}.")
            if subtasks:
                remaining.append(key)
                continue
            client.request("DELETE", f"/rest/api/3/issue/{quote(key, safe='')}")
            print(f"Ticket eliminado: {key}")
            progress = True
        if not progress:
            raise EvaluationError(
                "Hay subtareas no visibles o dependencias sin resolver; "
                "la base no se vaciará."
            )
        issues = remaining
    remaining_by_project = {key: client.list_issues(key) for key in projects}
    if any(remaining_by_project.values()):
        raise EvaluationError("Jira aún devuelve tickets; la base no se vaciará.")
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                "LOCK TABLE public.jira_evaluation_issues, public.page_evaluations, "
                "public.confluence_pages, public.confluence_spaces IN ACCESS EXCLUSIVE MODE"
            )
            cursor.execute(
                "SELECT confluence_page_id, title FROM public.confluence_pages ORDER BY id"
            )
            if cursor.fetchall() != pages:
                raise EvaluationError("Cambió el inventario de páginas; se cancela el vaciado.")
            if project is None:
                cursor.execute(
                    "SELECT DISTINCT jira_project_key FROM public.jira_evaluation_issues "
                    "ORDER BY jira_project_key"
                )
                if [row[0] for row in cursor.fetchall()] != projects:
                    raise EvaluationError(
                        "Cambió el inventario de proyectos; se cancela el vaciado."
                    )
            cursor.execute(
                "TRUNCATE TABLE public.jira_evaluation_issues, public.page_evaluations, "
                "public.confluence_pages, public.confluence_spaces RESTART IDENTITY"
            )
    print("Limpieza completada; esquema conservado.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--project", help="Proyecto Jira completo a vaciar")
    scope.add_argument(
        "--all-tracked-projects", action="store_true",
        help="Vaciar todos los proyectos registrados en jira_evaluation_issues",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", help="Confirmación exacta mostrada en la simulación")
    args = parser.parse_args()
    try:
        if args.project is not None and not re.fullmatch(r"[A-Z][A-Z0-9_]*", args.project):
            raise EvaluationError("Clave de proyecto Jira inválida.")
        required = ("CONFLUENCE_BASE_URL", "ATLASSIAN_EMAIL",
                    "ATLASSIAN_API_TOKEN", "DATABASE_URL")
        if any(not os.environ.get(name) for name in required):
            raise EvaluationError("Configura las variables: " + ", ".join(required))
        site = normalize_site_url(os.environ["CONFLUENCE_BASE_URL"])
        client = CleanupClient(site, os.environ["ATLASSIAN_EMAIL"],
                               os.environ["ATLASSIAN_API_TOKEN"])
        try:
            with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=15) as conn:
                cleanup(conn, client, args.project, args.apply, args.confirm)
        finally:
            client.session.close()
        return 0
    except (EvaluationError, psycopg.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
