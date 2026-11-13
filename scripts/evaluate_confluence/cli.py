"""Command-line interface for the Confluence evaluator."""

from __future__ import annotations

import argparse
import sys

import psycopg

from .config import EvaluationError, Settings
from .service import run_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evalúa páginas actuales de Confluence y guarda el historial diario."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="consultar Confluence y evaluar sin escribir en PostgreSQL",
    )
    args = parser.parse_args()
    try:
        settings = Settings.from_environment(dry_run=args.dry_run)
        return run_evaluation(settings)
    except (EvaluationError, psycopg.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
