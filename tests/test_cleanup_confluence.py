import unittest
from unittest.mock import MagicMock, Mock

from scripts.cleanup_confluence import CleanupClient, cleanup
from scripts.evaluate_confluence.config import EvaluationError


class CleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.cursor.fetchall.return_value = [("123", "Página")]
        self.client = Mock(site="https://example.com")
        self.client.list_issues.return_value = ["KAN-1"]

    def test_dry_run_never_deletes_or_truncates(self) -> None:
        cleanup(self.connection, self.client, "KAN", False, None)
        self.client.request.assert_not_called()
        self.assertEqual(self.cursor.execute.call_count, 1)

    def test_confirmation_is_required_before_deleting(self) -> None:
        with self.assertRaises(EvaluationError):
            cleanup(self.connection, self.client, "KAN", True, "incorrecta")
        self.client.request.assert_not_called()

    def test_remote_failure_preserves_database(self) -> None:
        self.client.request.side_effect = EvaluationError("HTTP 403")
        with self.assertRaises(EvaluationError):
            cleanup(self.connection, self.client, "KAN", True,
                    "BORRAR https://example.com KAN")
        self.assertEqual(self.cursor.execute.call_count, 1)

    def test_success_deletes_pages_and_issues_before_truncating(self) -> None:
        self.client.list_issues.side_effect = [["KAN-1"], []]
        self.client.request.side_effect = [{}, {"fields": {"subtasks": []}}, {}]
        cleanup(self.connection, self.client, "KAN", True,
                "BORRAR https://example.com KAN")
        paths = [call.args[:2] for call in self.client.request.call_args_list]
        self.assertEqual(paths, [
            ("DELETE", "/wiki/api/v2/pages/123"),
            ("GET", "/rest/api/3/issue/KAN-1"),
            ("DELETE", "/rest/api/3/issue/KAN-1"),
        ])
        sql = self.cursor.execute.call_args.args[0]
        self.assertIn("TRUNCATE TABLE", sql)
        self.assertNotIn("CASCADE", sql)

    def test_issue_listing_follows_pagination(self) -> None:
        client = CleanupClient("https://example.com", "user", "token")
        try:
            client.request = Mock(side_effect=[
                {"issues": [{"key": "KAN-1"}], "nextPageToken": "next"},
                {"issues": [{"key": "KAN-2"}], "isLast": True},
            ])
            self.assertEqual(client.list_issues("KAN"), ["KAN-1", "KAN-2"])
            self.assertEqual(
                client.request.call_args.kwargs["json"]["nextPageToken"], "next"
            )
        finally:
            client.session.close()

    def test_all_tracked_projects_are_listed_without_deleting(self) -> None:
        self.cursor.fetchall.side_effect = [
            [("123", "Página")], [("ABC",), ("KAN",)],
        ]
        self.client.list_issues.side_effect = [["ABC-1"], ["KAN-1"]]
        cleanup(self.connection, self.client, None, False, None)
        self.assertEqual(
            [call.args for call in self.client.list_issues.call_args_list],
            [("ABC",), ("KAN",)],
        )
        self.client.request.assert_not_called()

    def test_all_tracked_projects_are_deleted_before_truncating(self) -> None:
        pages = [("123", "Página")]
        projects = [("ABC",), ("KAN",)]
        self.cursor.fetchall.side_effect = [pages, projects, pages, projects]
        self.client.list_issues.side_effect = [["ABC-1"], ["KAN-1"], [], []]
        self.client.request.side_effect = [
            {}, {"fields": {"subtasks": []}}, {},
            {"fields": {"subtasks": []}}, {},
        ]
        cleanup(self.connection, self.client, None, True,
                "BORRAR https://example.com PROYECTOS-BD:ABC,KAN")
        deletions = [
            call.args[1] for call in self.client.request.call_args_list
            if call.args[0] == "DELETE"
        ]
        self.assertEqual(deletions, [
            "/wiki/api/v2/pages/123",
            "/rest/api/3/issue/ABC-1",
            "/rest/api/3/issue/KAN-1",
        ])
        self.assertIn("TRUNCATE TABLE", self.cursor.execute.call_args.args[0])

    def test_empty_project_inventory_does_not_query_jira(self) -> None:
        self.cursor.fetchall.side_effect = [[("123", "Página")], []]
        cleanup(self.connection, self.client, None, False, None)
        self.client.list_issues.assert_not_called()
        self.client.request.assert_not_called()
