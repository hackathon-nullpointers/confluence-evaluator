import os
import unittest
from contextlib import redirect_stderr
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from scripts.evaluate_confluence.config import (
    EvaluationError,
    Settings,
)
from scripts.evaluate_confluence.confluence import ConfluenceClient
from scripts.evaluate_confluence.documents import (
    extract_document,
    extract_item_document,
)
from scripts.evaluate_confluence.link_checker import (
    normalize_web_links,
    public_addresses,
)
from scripts.evaluate_confluence.ports import JiraIssueResult
from scripts.evaluate_confluence.copilot import (
    AGENT_NAME,
    AGENT_SKILLS,
    SKILLS_DIR,
    CopilotEvaluator,
    load_agent_config,
    parse_frontmatter,
    validate_comment_batch,
    validate_evaluation_feedback,
)
from scripts.evaluate_confluence.database import EvaluationDatabase
from scripts.evaluate_confluence.jira import JiraClient
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
from scripts.evaluate_confluence.service import (
    EvaluationService,
    analyze_pages,
    collect_page_work,
)


def test_settings() -> Settings:
    return Settings(
        site_url="https://bcphackaton.atlassian.net",
        atlassian_email="evaluator@example.com",
        atlassian_token="atlassian-token",
        database_url="postgresql://localhost/test",
        copilot_token="oauth-token",
        copilot_model="gpt-4.1",
        evaluation_date=date(2026, 11, 13),
        dry_run=False,
        jira_project_key="KAN",
    )


class EvaluationScoringTests(unittest.TestCase):
    def test_run_excludes_personal_spaces_and_their_pages(self) -> None:
        api = Mock()
        shared = {"id": "1", "key": "ARQ", "type": "global"}
        api.get_spaces.return_value = [
            shared,
            {"id": "2", "key": "personal", "type": "personal"},
            {"id": "3", "key": "~user"},
        ]
        shared_page = {"id": "10", "spaceId": "1"}
        api.get_pages.return_value = [
            shared_page,
            {"id": "20", "spaceId": "2"},
            {"id": "30", "spaceId": "3"},
        ]
        service = EvaluationService(
            test_settings(),
            confluence_factory=Mock(return_value=api),
            repository_factory=Mock(
                return_value=Mock(completed_page_ids=Mock(return_value=set()))
            ),
            spell_checker_factory=Mock(),
        )
        with (
            patch(
                "scripts.evaluate_confluence.service.collect_page_work",
                return_value=[],
            ) as collect,
            patch(
                "scripts.evaluate_confluence.service.analyze_pages",
                new_callable=AsyncMock,
            ),
            patch.object(service, "_persist") as persist,
            patch.object(service, "_publish_jira_issues", return_value=0),
        ):
            self.assertEqual(service.run(), 0)

        self.assertEqual(collect.call_args.args[1], [shared_page])
        self.assertEqual(collect.call_args.args[2], {"1": shared})
        persist.assert_called_once_with([shared], [])
        api.close.assert_called_once_with()

    def test_completed_page_ids_only_queries_completed_for_requested_date(self) -> None:
        database = object.__new__(EvaluationDatabase)
        database.connection = MagicMock()
        cursor = database.connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [("123",), ("456",)]
        day = date(2026, 11, 13)

        self.assertEqual(database.completed_page_ids(day), {"123", "456"})
        query, parameters = cursor.execute.call_args.args
        self.assertIn("evaluation.evaluation_status = 'completed'", query)
        self.assertIn("evaluation.evaluation_date = %s", query)
        self.assertEqual(parameters, (day,))

    def test_run_skips_completed_pages_before_collecting(self) -> None:
        api = Mock()
        api.get_spaces.return_value = [{"id": "1", "key": "ARQ"}]
        api.get_pages.return_value = [
            {"id": "done", "spaceId": "1"},
            {"id": "new", "spaceId": "1"},
            {"id": "retry-failed", "spaceId": "1"},
        ]
        database = Mock()
        database.completed_page_ids.return_value = {"done"}
        service = EvaluationService(
            test_settings(), confluence_factory=Mock(return_value=api),
            repository_factory=Mock(return_value=database),
            spell_checker_factory=Mock(),
        )
        with (
            patch("scripts.evaluate_confluence.service.collect_page_work",
                  return_value=[]) as collect,
            patch("scripts.evaluate_confluence.service.analyze_pages",
                  new_callable=AsyncMock),
            patch.object(service, "_persist"),
            patch.object(service, "_publish_jira_issues", return_value=0),
        ):
            self.assertEqual(service.run(), 0)
        self.assertEqual(
            [page["id"] for page in collect.call_args.args[1]], ["new", "retry-failed"]
        )
        database.completed_page_ids.assert_called_once_with(date(2026, 11, 13))
        database.close.assert_called_once_with()

    def test_run_does_not_evaluate_or_write_when_all_pages_completed(self) -> None:
        api = Mock()
        api.get_spaces.return_value = [{"id": "1", "key": "ARQ"}]
        api.get_pages.return_value = [{"id": "done", "spaceId": "1"}]
        database = Mock()
        database.completed_page_ids.return_value = {"done"}
        evaluator_factory = Mock()
        service = EvaluationService(
            test_settings(), confluence_factory=Mock(return_value=api),
            repository_factory=Mock(return_value=database),
            evaluator_factory=evaluator_factory,
        )
        self.assertEqual(service.run(), 0)
        evaluator_factory.assert_not_called()
        database.persist.assert_not_called()
        api.get_page_detail.assert_not_called()
        api.close.assert_called_once_with()

    def test_headless_run_defaults_to_verified_copilot_model(self) -> None:
        environment = {
            "ATLASSIAN_EMAIL": "evaluator@example.com",
            "ATLASSIAN_API_TOKEN": "atlassian-token",
            "COPILOT_GITHUB_TOKEN": "oauth-token",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_environment(dry_run=True)
        self.assertEqual(settings.copilot_model, "gpt-4.1")
        self.assertEqual(settings.jira_project_key, "KAN")

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
        expected = ((1, 80, 100), (3, 60, 80), (6, 30, 60), (12, 0, 30))

        for months, boundary_score, newer_score in expected:
            with self.subTest(months=months):
                boundary = subtract_calendar_months(as_of, months)
                self.assertEqual(freshness_score(boundary, as_of), boundary_score)
                self.assertEqual(
                    freshness_score(boundary + timedelta(microseconds=1), as_of),
                    newer_score,
                )

    def test_weighted_total_applies_all_criteria_and_weights(self) -> None:
        scores = {criterion: 100.0 for criterion in WEIGHTS}
        self.assertEqual(weighted_total(scores), 100.0)

        scores["links_score"] = 0.0
        self.assertEqual(weighted_total(scores), 85.0)

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
        self.assertAlmostEqual(comment_score(3.0, 1.0), 100 * 4 / 6)
        self.assertEqual(comment_score(0.0, 0.0), 50.0)
        self.assertAlmostEqual(comment_score(1.0, 0.0), 100 * 2 / 3)
        self.assertAlmostEqual(comment_score(0.0, 1.0), 100 / 3)
        self.assertGreater(comment_score(10.0, 0.0), comment_score(1.0, 0.0))

    def test_spelling_score_reduces_proportionally(self) -> None:
        self.assertEqual(spelling_score(100, 5), 75.0)
        self.assertEqual(spelling_score(100, 10), 50.0)
        self.assertEqual(spelling_score(100, 30), 0.0)
        self.assertEqual(spelling_score(100, 0), 100.0)
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

    def test_evaluation_feedback_requires_reason_insights_and_recommendations(self) -> None:
        feedback = validate_evaluation_feedback(
            {
                "evaluation_reason": "Los enlaces reducen el puntaje ponderado.",
                "insights": ["Hay enlaces inválidos."],
                "recommendations": ["Revisar los enlaces marcados como inválidos."],
            }
        )
        self.assertEqual(feedback["insights"], ["Hay enlaces inválidos."])
        with self.assertRaisesRegex(EvaluationError, "recommendations"):
            validate_evaluation_feedback(
                {
                    "evaluation_reason": "Puntaje bajo.",
                    "insights": ["Hay enlaces inválidos."],
                    "recommendations": [],
                }
            )

    def test_jira_issue_creation_adds_project_type_and_idempotency_label(self) -> None:
        jira = JiraClient(test_settings())
        page = {
            "page_id": "1343489",
            "title": "Excepciones de análisis estático",
            "page_url": "https://bcphackaton.atlassian.net/wiki/spaces/DSEC/pages/1343489",
            "total_score": 71.5,
            "scores": {
                "author_exists_score": 100.0,
                "comments_score": 50.0,
                "freshness_score": 75.0,
                "structure_score": 60.0,
                "likes_score": 50.0,
                "spelling_score": 80.0,
                "links_score": 40.0,
            },
            "evaluation_feedback": {
                "evaluation_reason": "Los enlaces aportan el menor puntaje ponderado.",
                "insights": ["Se encontraron enlaces inválidos."],
                "recommendations": ["Corregir los enlaces rotos."],
            },
        }

        with patch.object(
            jira,
            "_request_json",
            side_effect=[{"issues": []}, {"key": "KAN-123"}],
        ) as request:
            issue_key = jira.upsert_evaluation_issue(page, date(2026, 11, 13))

        self.assertEqual(issue_key.key, "KAN-123")
        self.assertEqual(issue_key.url, "https://bcphackaton.atlassian.net/browse/KAN-123")
        self.assertEqual(issue_key.action, "created")
        create_call = request.call_args_list[1]
        self.assertEqual(create_call.args[0:2], ("POST", "issue"))
        fields = create_call.args[2]["fields"]
        self.assertEqual(fields["project"], {"key": "KAN"})
        self.assertEqual(fields["issuetype"], {"name": "Task"})
        self.assertEqual(fields["labels"], ["confluence-eval-1343489-20261113"])
        self.assertIn("Corregir los enlaces rotos", str(fields["description"]))

    def test_jira_issue_upsert_updates_matching_issue(self) -> None:
        jira = JiraClient(test_settings())
        page = {
            "page_id": "1343489",
            "title": "Guía",
            "page_url": "https://example.com/page",
            "total_score": 70.0,
            "scores": {
                "author_exists_score": 100.0,
                "comments_score": 50.0,
                "freshness_score": 75.0,
                "structure_score": 60.0,
                "likes_score": 50.0,
                "spelling_score": 80.0,
                "links_score": 40.0,
            },
            "evaluation_feedback": {
                "evaluation_reason": "Puntaje bajo.",
                "insights": ["Faltan enlaces válidos."],
                "recommendations": ["Agregar fuentes vigentes."],
            },
        }

        with patch.object(
            jira,
            "_request_json",
            side_effect=[{"issues": [{"key": "KAN-123"}]}, {}],
        ) as request:
            issue_key = jira.upsert_evaluation_issue(page, date(2026, 11, 13))

        self.assertEqual(issue_key.key, "KAN-123")
        self.assertEqual(issue_key.action, "updated")
        self.assertEqual(request.call_args_list[1].args[:2], ("PUT", "issue/KAN-123"))

    def test_jira_publishing_only_sends_failed_threshold_pages(self) -> None:
        jira = Mock()
        jira.upsert_evaluation_issue.return_value = JiraIssueResult(
            "KAN-123",
            "https://bcphackaton.atlassian.net/browse/KAN-123",
            "created",
        )
        database = Mock()
        service = EvaluationService(
            test_settings(),
            jira_factory=Mock(return_value=jira),
            repository_factory=Mock(return_value=database),
        )
        pages = [
            {
                "page_id": "low",
                "title": "Bajo",
                "space_key": "DSEC",
                "total_score": 80.0,
                "failure": None,
                "evaluation_feedback": {
                    "evaluation_reason": "Puntaje bajo.",
                    "insights": ["Faltan enlaces válidos."],
                    "recommendations": ["Agregar fuentes vigentes."],
                },
            },
            {"page_id": "above-limit", "title": "Superior", "space_key": "DSEC", "total_score": 80.01, "failure": None, "evaluation_feedback": {"evaluation_reason": "No publicar"}},
            {"page_id": "failed", "title": "Fallida", "space_key": "DSEC", "total_score": 20.0, "failure": "Error"},
        ]

        failures = service._publish_jira_issues(pages)

        self.assertEqual(failures, 0)
        jira.upsert_evaluation_issue.assert_called_once_with(
            pages[0], date(2026, 11, 13)
        )
        database.record_jira_sync.assert_called_once_with(
            "low",
            date(2026, 11, 13),
            "synced",
            "created",
            "KAN-123",
            "https://bcphackaton.atlassian.net/browse/KAN-123",
            None,
        )
        database.close.assert_called_once_with()
        jira.close.assert_called_once_with()

    def test_jira_failure_is_recorded_for_retry(self) -> None:
        jira = Mock()
        jira.upsert_evaluation_issue.side_effect = EvaluationError("Jira HTTP 503")
        database = Mock()
        service = EvaluationService(
            test_settings(),
            jira_factory=Mock(return_value=jira),
            repository_factory=Mock(return_value=database),
        )
        page = {
            "page_id": "low",
            "title": "Bajo",
            "space_key": "DSEC",
            "total_score": 60.0,
            "failure": None,
            "evaluation_feedback": {
                "evaluation_reason": "Puntaje bajo.",
                "insights": ["Faltan enlaces válidos."],
                "recommendations": ["Agregar fuentes vigentes."],
            },
        }

        with redirect_stderr(StringIO()):
            failures = service._publish_jira_issues([page])

        self.assertEqual(failures, 1)
        database.record_jira_sync.assert_called_once_with(
            "low",
            date(2026, 11, 13),
            "failed",
            "failed",
            None,
            None,
            "Jira HTTP 503",
        )

    def test_persist_stores_jira_trace_and_feedback_snapshot(self) -> None:
        database = object.__new__(EvaluationDatabase)
        database.connection = MagicMock()
        cursor = database.connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [(1,), (2,), (3,)]
        feedback = {
            "evaluation_reason": "Los enlaces reducen el puntaje.",
            "insights": ["Hay enlaces inválidos."],
            "recommendations": ["Reparar los enlaces."],
        }
        page = {
            "page_id": "page-1",
            "space_id": "space-1",
            "title": "Guía",
            "page_url": "https://example.com/page",
            "confluence_status": "current",
            "failure": None,
            "author_account_id": "author-1",
            "author_display_name": "Ada",
            "author_email": "ada@example.com",
            "updated_at": datetime(2026, 11, 12, tzinfo=UTC),
            "likes_count": 1,
            "word_count": 100,
            "spelling_errors_count": 2,
            "valid_links_count": 1,
            "invalid_links_count": 2,
            "unchecked_links_count": 0,
            "comparison_group": "global",
            "scores": {criterion: 80.0 for criterion in WEIGHTS},
            "total_score": 80.0,
            "comment_metrics": {},
            "evaluation_feedback": feedback,
        }

        database.persist(
            [{"id": "space-1", "key": "DSEC", "name": "DevSecOps"}],
            [page],
            date(2026, 11, 13),
            "gpt-4.1",
            "KAN",
        )

        trace_query, trace_values = cursor.execute.call_args_list[-1].args
        self.assertIn("INSERT INTO jira_evaluation_issues", trace_query)
        self.assertEqual(trace_values[0:3], (3, "KAN", "pending"))
        self.assertEqual(trace_values[4:], (None, None))
        self.assertEqual(trace_values[3].obj, feedback)

    def test_jira_sync_record_updates_status_and_attempt_metadata(self) -> None:
        database = object.__new__(EvaluationDatabase)
        database.connection = MagicMock()
        cursor = database.connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (3,)

        database.record_jira_sync(
            "page-1",
            date(2026, 11, 13),
            "synced",
            "created",
            "KAN-123",
            "https://bcphackaton.atlassian.net/browse/KAN-123",
            None,
        )

        query, values = cursor.execute.call_args.args
        self.assertIn("sync_attempt_count = tracking.sync_attempt_count + 1", query)
        self.assertIn("last_synced_at = CASE", query)
        self.assertEqual(
            values[:4],
            (
                "KAN-123",
                "https://bcphackaton.atlassian.net/browse/KAN-123",
                "synced",
                "created",
            ),
        )
        self.assertIsInstance(values[4], datetime)
        self.assertEqual(values[5], "synced")
        self.assertIsInstance(values[6], datetime)
        self.assertIsNone(values[7])
        self.assertEqual(values[8:], ("page-1", date(2026, 11, 13)))

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

    def test_links_score_requires_verified_links(self) -> None:
        self.assertAlmostEqual(links_score(3, 1, 10), 100 * 3 / 14)
        self.assertEqual(links_score(0, 0, 0), 50.0)
        self.assertEqual(links_score(0, 0, 2), 0.0)
        self.assertEqual(links_score(2, 0, 0), 100.0)
        self.assertEqual(links_score(0, 2, 0), 0.0)

    def test_user_lookup_caches_profile_and_uses_account_id_endpoint(self) -> None:
        profile = {
            "accountId": "author-1",
            "displayName": "Ada Lovelace",
            "email": "ada@example.com",
        }
        client = object.__new__(ConfluenceClient)
        client.site_url = "https://confluence.example"
        client._user_cache = {}

        with patch.object(ConfluenceClient, "get_json", return_value=profile) as get_json:
            first = client.get_user("author-1")
            second = client.get_user("author-1")

        self.assertEqual(first, profile)
        self.assertIs(second, first)
        get_json.assert_called_once_with(
            "https://confluence.example/wiki/rest/api/user",
            {"accountId": "author-1"},
            allow_not_found=True,
        )

    def test_page_url_includes_wiki_context_for_confluence_webui_paths(self) -> None:
        client = object.__new__(ConfluenceClient)
        client.site_url = "https://bcphackaton.atlassian.net"
        title_path = "DSEC/pages/1343489/Excepciones+de+an+lisis+est+tico"

        self.assertEqual(
            client.page_url(
                {"id": "1343489", "_links": {"webui": f"/spaces/{title_path}"}}
            ),
            f"https://bcphackaton.atlassian.net/wiki/spaces/{title_path}",
        )
        self.assertEqual(
            client.page_url(
                {"id": "1343489", "_links": {"webui": f"/wiki/spaces/{title_path}"}}
            ),
            f"https://bcphackaton.atlassian.net/wiki/spaces/{title_path}",
        )

    def test_page_work_includes_author_profile_when_confluence_exposes_it(self) -> None:
        api = Mock()
        api.get_user.return_value = {
            "displayName": "Ada Lovelace",
            "email": "ada@example.com",
        }
        api.page_url.return_value = "https://confluence.example/page"
        api.get_page_comments.return_value = []
        api.get_likes_count.return_value = 2
        page = {
            "id": "page-1",
            "spaceId": "space-1",
            "title": "Design",
            "authorId": "author-1",
            "version": {"authorId": "author-1", "createdAt": "2026-11-12T10:00:00Z"},
            "body": {"storage": {"value": "<p>Texto de ejemplo</p>"}},
        }

        with patch(
            "scripts.evaluate_confluence.service.spelling_counts",
            return_value=(3, 0),
        ):
            result = collect_page_work(
                api,
                [page],
                {"space-1": {"id": "space-1", "key": "ARQ", "name": "Arquitectura"}},
                Mock(),
                link_checker=lambda links: (0, 0, 0),
            )

        self.assertEqual(result[0]["author_display_name"], "Ada Lovelace")
        self.assertEqual(result[0]["author_email"], "ada@example.com")
        api.get_user.assert_called_once_with("author-1")

    def test_profile_lookup_failure_does_not_fail_page_evaluation(self) -> None:
        api = Mock()
        api.get_user.side_effect = EvaluationError("HTTP 403")
        api.page_url.return_value = "https://confluence.example/page"
        api.get_page_comments.return_value = []
        api.get_likes_count.return_value = 0
        page = {
            "id": "page-1",
            "spaceId": "space-1",
            "title": "Design",
            "authorId": "author-1",
            "version": {"authorId": "author-1", "createdAt": "2026-11-12T10:00:00Z"},
            "body": {"storage": {"value": "<p>Texto de ejemplo</p>"}},
        }

        with (
            patch(
                "scripts.evaluate_confluence.service.spelling_counts",
                return_value=(3, 0),
            ),
            redirect_stderr(StringIO()) as error_output,
        ):
            result = collect_page_work(
                api,
                [page],
                {"space-1": {"id": "space-1", "key": "ARQ", "name": "Arquitectura"}},
                Mock(),
                link_checker=lambda links: (0, 0, 0),
            )

        self.assertIsNone(result[0]["author_display_name"])
        self.assertIsNone(result[0]["author_email"])
        self.assertIsNone(result[0]["failure"])
        self.assertIn("HTTP 403", error_output.getvalue())


class CopilotAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_feedback_includes_threshold_but_excludes_higher_scores(self) -> None:
        evaluator = MagicMock()
        evaluator.__aenter__ = AsyncMock(return_value=evaluator)
        evaluator.__aexit__ = AsyncMock(return_value=None)
        evaluator.analyze_structure = AsyncMock(return_value={})
        evaluator.classify_comments = AsyncMock(return_value={})
        evaluator.explain_evaluation = AsyncMock(return_value={"evaluation_reason": "Mejorar"})
        pages = [
            {"failure": None, "title": "Límite", "comments": [], "total_score": 80.0},
            {"failure": None, "title": "Superior", "comments": [], "total_score": 80.01},
        ]
        with patch("scripts.evaluate_confluence.service.prepare_scores"):
            await analyze_pages(pages, "token", "model", Mock(return_value=evaluator))

        evaluator.explain_evaluation.assert_awaited_once_with(pages[0])
        self.assertIn("evaluation_feedback", pages[0])
        self.assertNotIn("evaluation_feedback", pages[1])

    def test_agent_config_loads_prompt_and_skills(self) -> None:
        agent = load_agent_config()

        self.assertEqual(agent["name"], AGENT_NAME)
        self.assertEqual(agent["skills"], list(AGENT_SKILLS))
        self.assertNotIn("---", agent["prompt"].splitlines()[0])
        for skill in AGENT_SKILLS:
            self.assertIn(skill, agent["prompt"])

    def test_every_agent_skill_declares_its_directory_name(self) -> None:
        for skill in AGENT_SKILLS:
            text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(text)
            self.assertEqual(metadata["name"], skill)
            self.assertTrue(metadata["description"])
            self.assertTrue(body)

    def test_frontmatter_is_required(self) -> None:
        with self.assertRaises(EvaluationError):
            parse_frontmatter("sin frontmatter")

    async def test_ask_sends_task_payload_to_the_agent(self) -> None:
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.send_and_wait = AsyncMock(
            return_value=Mock(data=Mock(content='{"comments": []}'))
        )
        evaluator = CopilotEvaluator("token", "gpt-4.1")
        evaluator.client.create_session = AsyncMock(return_value=session)

        result = await evaluator._ask("comment_classification", {"page_title": "A"})

        options = evaluator.client.create_session.call_args.kwargs
        self.assertEqual(options["agent"], AGENT_NAME)
        self.assertEqual(options["skill_directories"], [str(SKILLS_DIR)])
        self.assertIn("gitbot", options["disabled_skills"])
        self.assertEqual(result, {"comments": []})
        message = session.send_and_wait.call_args.args[0]
        self.assertIn('"task": "comment_classification"', message)
        self.assertIn('"page_title": "A"', message)


if __name__ == "__main__":
    unittest.main()
