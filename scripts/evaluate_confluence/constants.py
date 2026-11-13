"""Shared evaluator limits, prompts, and scoring weights."""

from __future__ import annotations


PROMPT_VERSION = "v3"

SCORING_VERSION = "v2"

COPILOT_MODEL_DEFAULT = "gpt-4.1"

COMMENT_BATCH_SIZE = 15

MAX_PAGE_TEXT_CHARS = 24_000

MAX_COMMENT_CHARS = 4_000

MAX_LINKS_PER_PAGE = 100

LINK_TIMEOUT = (5, 12)

MAX_REDIRECTS = 5

MIN_PEER_GROUP_SIZE = 5

WEIGHTS = {
    "author_exists_score": 5,
    "comments_score": 5,
    "freshness_score": 15,
    "structure_score": 35,
    "likes_score": 5,
    "spelling_score": 20,
    "links_score": 15,
}

DOMAINS = {
    "architecture",
    "jira_governance",
    "devsecops",
    "testing",
    "general",
}

DOCUMENT_TYPES = {
    "decision_record",
    "policy",
    "standard",
    "procedure",
    "guide",
    "strategy",
    "test_plan",
    "reference",
    "other",
}

STRUCTURE_DIMENSIONS = (
    "heading_hierarchy",
    "section_coverage",
    "logical_flow",
    "scannability",
    "format_consistency",
)

DEFAULT_SPELLING_ALLOWLIST = {
    "ACID",
    "API",
    "APIs",
    "CI",
    "Confluence",
    "DevSecOps",
    "HTTP",
    "HTTPS",
    "ID",
    "IDs",
    "JSON",
    "Jira",
    "OAuth",
    "OWASP",
    "PostgreSQL",
    "REST",
    "SQL",
    "UTC",
    "UUID",
    "WCAG",
}
