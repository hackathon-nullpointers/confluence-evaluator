import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from scripts.evaluate_confluence.config import (
    EvaluationError,
    Settings,
)
from scripts.evaluate_confluence.documents import (
    extract_document,
    extract_item_document,
)
from scripts.evaluate_confluence.link_checker import (
    normalize_web_links,
    public_addresses,
)
from scripts.evaluate_confluence.copilot import validate_comment_batch
from scripts.evaluate_confluence.scoring import (
    WEIGHTS,
    assign_comparison_groups,
    comment_score,
    freshness_score,
    links_score,
    percentile_likes_scores,
    spelling_score,
    subtract_calendar_months,
    weighted_total,
)


class EvaluationScoringTests(unittest.TestCase):
    def test_headless_run_defaults_to_verified_copilot_model(self) -> None:
        environment = {
            "ATLASSIAN_EMAIL": "evaluator@example.com",
            "ATLASSIAN_API_TOKEN": "atlassian-token",
            "COPILOT_GITHUB_TOKEN": "oauth-token",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_environment(dry_run=True)
        self.assertEqual(settings.copilot_model, "gpt-4.1")

    def test_headless_run_requires_copilot_sdk_token(self) -> None:
        environment = {
            "ATLASSIAN_EMAIL": "evaluator@example.com",
            "ATLASSIAN_API_TOKEN": "atlassian-token",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(EvaluationError, "COPILOT_GITHUB_TOKEN"):
                Settings.from_environment(dry_run=True)

    def test_freshness_uses_strict_calendar_month_boundaries(self) -> None:
        as_of = datetime(2025, 6, 30, tzinfo=UTC)
        expected = ((3, 75), (6, 50), (12, 25), (24, 0))

        for months, boundary_score in expected:
            with self.subTest(months=months):
                boundary = subtract_calendar_months(as_of, months)
                self.assertEqual(freshness_score(boundary, as_of), boundary_score)
                self.assertEqual(
                    freshness_score(boundary + timedelta(microseconds=1), as_of),
                    min(100, boundary_score + 25),
                )

    def test_weighted_total_applies_all_criteria_and_weights(self) -> None:
        scores = {criterion: 100.0 for criterion in WEIGHTS}
        self.assertEqual(weighted_total(scores), 100.0)

        scores["links_score"] = 0.0
        self.assertEqual(weighted_total(scores), 75.0)

    def test_weighted_total_rejects_missing_or_out_of_range_scores(self) -> None:
        with self.assertRaisesRegex(EvaluationError, "Faltan puntajes"):
            weighted_total({})
        with self.assertRaisesRegex(EvaluationError, "entre 0 y 100"):
            weighted_total(
                {
                    **{criterion: 100.0 for criterion in WEIGHTS},
                    "likes_score": 101,
                }
            )

    def test_comment_score_weights_relevance_and_has_neutral_fallback(self) -> None:
        self.assertEqual(comment_score(3.0, 1.0), 75.0)
        self.assertEqual(comment_score(0.0, 0.0), 50.0)

    def test_spelling_score_reduces_proportionally(self) -> None:
        self.assertEqual(spelling_score(100, 5), 95.0)
        self.assertEqual(spelling_score(0, 0), 100.0)

    def test_likes_percentile_averages_tied_ranks(self) -> None:
        pages = [
            {"comparison_group": "guide", "likes_count": likes}
            for likes in (0, 10, 10)
        ]
        percentile_likes_scores(pages)
        self.assertEqual(
            [page["scores"]["likes_score"] for page in pages],
            [0.0, 75.0, 75.0],
        )

    def test_like_groups_fall_back_to_document_type(self) -> None:
        pages = [
            {
                "analysis": {
                    "domain": domain,
                    "document_type": "guide",
                }
            }
            for domain in ("architecture", "architecture", "testing", "testing", "general")
        ]
        assign_comparison_groups(pages)
        self.assertEqual({page["comparison_group"] for page in pages}, {"type:guide"})

    def test_comment_batch_requires_exact_indexes_and_valid_values(self) -> None:
        result = validate_comment_batch(
            {
                "comments": [
                    {"index": 4, "sentiment": "positive", "relevance": 0.7},
                    {"index": 5, "sentiment": "neutral", "relevance": 0},
                ]
            },
            {4, 5},
        )
        self.assertEqual(result[4], ("positive", 0.7))
        with self.assertRaisesRegex(EvaluationError, "no clasificó todos"):
            validate_comment_batch(
                {"comments": [{"index": 4, "sentiment": "positive", "relevance": 1}]},
                {4, 5},
            )

    def test_extract_document_collects_structure_and_ignores_code_for_spelling(self) -> None:
        document = extract_document(
            "<h1>Guía</h1><p>Texto visible</p><ul><li>Paso</li></ul>"
            "<table><tr><td>Dato</td></tr></table><pre>erróneo</pre>"
            '<a href="https://example.com">Referencia</a>'
        )
        self.assertEqual(document.headings, [{"level": 1, "text": "Guía"}])
        self.assertEqual(document.list_count, 1)
        self.assertEqual(document.table_count, 1)
        self.assertIn("erróneo", document.text)
        self.assertNotIn("erróneo", document.spelling_text)
        self.assertEqual(document.links, ["https://example.com"])

    def test_extract_atlas_doc_format_supports_live_document_body(self) -> None:
        page = {
            "body": {
                "atlas_doc_format": {
                    "value": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "heading",
                                "attrs": {"level": 1},
                                "content": [{"type": "text", "text": "Guía"}],
                            },
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Referencia",
                                        "marks": [
                                            {
                                                "type": "link",
                                                "attrs": {
                                                    "href": "https://example.com"
                                                },
                                            }
                                        ],
                                    }
                                ],
                            },
                            {
                                "type": "bulletList",
                                "content": [
                                    {
                                        "type": "listItem",
                                        "content": [
                                            {
                                                "type": "paragraph",
                                                "content": [
                                                    {"type": "text", "text": "Paso"}
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            },
                            {
                                "type": "codeBlock",
                                "content": [
                                    {"type": "text", "text": "typo_in_code"}
                                ],
                            },
                        ],
                    }
                }
            }
        }

        document = extract_item_document(page)

        self.assertEqual(document.headings, [{"level": 1, "text": "Guía"}])
        self.assertEqual(document.list_count, 1)
        self.assertEqual(document.links, ["https://example.com"])
        self.assertIn("typo_in_code", document.text)
        self.assertNotIn("typo_in_code", document.spelling_text)

    def test_public_address_validation_handles_ipv4_and_rejects_loopback(self) -> None:
        self.assertTrue(public_addresses("8.8.8.8", 443))
        self.assertFalse(public_addresses("127.0.0.1", 443))

    def test_normalize_web_links_deduplicates_and_ignores_non_web_schemes(self) -> None:
        links = normalize_web_links(
            [
                "../guia",
                "https://example.com/a#section",
                "https://example.com/a",
                "mailto:a@b.com",
                "http://[::1",
            ],
            "https://confluence.example/wiki/page",
        )
        self.assertEqual(
            links,
            [
                "https://confluence.example/guia",
                "https://example.com/a",
            ],
        )

    def test_links_score_excludes_unchecked_links(self) -> None:
        self.assertEqual(links_score(3, 1, 10), 75.0)
        self.assertEqual(links_score(0, 0, 0), 100.0)
        self.assertEqual(links_score(0, 0, 2), 50.0)


if __name__ == "__main__":
    unittest.main()
