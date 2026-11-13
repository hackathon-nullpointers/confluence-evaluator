"""Runtime configuration and shared evaluation errors."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urlsplit, urlunsplit

from .constants import COPILOT_MODEL_DEFAULT


class EvaluationError(RuntimeError):
    """Raised for configuration, API, model, or persistence errors."""

@dataclass(frozen=True)
class Settings:
    site_url: str
    atlassian_email: str
    atlassian_token: str
    database_url: str
    copilot_token: str
    copilot_model: str
    evaluation_date: date
    dry_run: bool

    @classmethod
    def from_environment(cls, dry_run: bool) -> Settings:
        site_url = normalize_site_url(
            os.environ.get(
                "CONFLUENCE_BASE_URL", "https://bcphackaton.atlassian.net"
            )
        )
        email = os.environ.get("ATLASSIAN_EMAIL")
        token = os.environ.get("ATLASSIAN_API_TOKEN")
        copilot_token = (
            os.environ.get("COPILOT_GITHUB_TOKEN")
            or os.environ.get("GH_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
        )
        database_url = os.environ.get("DATABASE_URL")

        missing = [
            name
            for name, value in (
                ("ATLASSIAN_EMAIL", email),
                ("ATLASSIAN_API_TOKEN", token),
                ("COPILOT_GITHUB_TOKEN", copilot_token),
            )
            if not value
        ]
        if not dry_run and not database_url:
            missing.append("DATABASE_URL")
        if missing:
            raise EvaluationError(
                "Faltan variables de entorno requeridas: " + ", ".join(missing)
            )

        raw_date = os.environ.get("EVALUATION_DATE")
        try:
            evaluation_date = (
                date.fromisoformat(raw_date)
                if raw_date
                else datetime.now(UTC).date()
            )
        except ValueError as error:
            raise EvaluationError("EVALUATION_DATE debe tener formato YYYY-MM-DD.") from error

        return cls(
            site_url=site_url,
            atlassian_email=email or "",
            atlassian_token=token or "",
            database_url=database_url or "",
            copilot_token=copilot_token or "",
            copilot_model=os.environ.get("COPILOT_MODEL", COPILOT_MODEL_DEFAULT),
            evaluation_date=evaluation_date,
            dry_run=dry_run,
        )

def normalize_site_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise EvaluationError("CONFLUENCE_BASE_URL debe ser una URL HTTPS válida.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise EvaluationError(
            "CONFLUENCE_BASE_URL no debe incluir credenciales, query ni fragmento."
        )
    path = parsed.path.rstrip("/")
    if path.endswith("/wiki/home"):
        path = path[: -len("/wiki/home")]
    elif path.endswith("/wiki"):
        path = path[: -len("/wiki")]
    if path:
        raise EvaluationError(
            "CONFLUENCE_BASE_URL debe ser el dominio del sitio o terminar en /wiki/home."
        )
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
