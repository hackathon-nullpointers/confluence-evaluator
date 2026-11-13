import asyncio
import base64
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from scripts.confluence_mcp import ConfluenceReader, mcp


class ConfluenceMCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.requests = []
        self.responses = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self.responses.pop(0)

        self.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.reader = ConfluenceReader("https://example.com", self.http)

    async def asyncTearDown(self) -> None:
        await self.http.aclose()

    async def test_spaces_fetch_only_one_batch_and_follow_bound_cursor(self) -> None:
        self.responses = [
            httpx.Response(200, json={
                "results": [{"id": "1", "key": "OPS", "name": "Operación"}],
                "_links": {"next": "/wiki/api/v2/spaces?cursor=abc&limit=25"},
            }),
            httpx.Response(200, json={"results": [], "_links": {}}),
        ]
        first = await self.reader.spaces(25, None)
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(first["hasMore"])
        second = await self.reader.spaces(25, first["nextCursor"])
        self.assertFalse(second["hasMore"])
        self.assertEqual(self.requests[1].url.params["cursor"], "abc")
        with self.assertRaisesRegex(ValueError, "Cursor"):
            await self.reader.spaces(10, first["nextCursor"])
        self.assertEqual(len(self.requests), 2)

    async def test_search_escapes_cql_and_cleans_excerpt(self) -> None:
        self.responses = [httpx.Response(200, json={"results": [{
            "content": {
                "id": "123", "title": "Ambiente", "space": {"key": "OPS"},
                "_links": {"webui": "/spaces/OPS/pages/123"},
            },
            "excerpt": '<span class="search-highlight">Ambiente</span> de pruebas',
        }]})]
        result = await self.reader.search('ambiente" OR type=blogpost', ["OPS"], 10, None)
        params = self.requests[0].url.params
        self.assertIn('text~"ambiente\\" OR type=blogpost"', params["cql"])
        self.assertIn('space IN ("OPS")', params["cql"])
        self.assertEqual(params["excerpt"], "highlight")
        self.assertEqual(result["results"][0]["excerpt"], "Ambiente de pruebas")
        self.assertEqual(result["results"][0]["url"],
                         "https://example.com/wiki/spaces/OPS/pages/123")

    async def test_search_follows_start_and_link_header(self) -> None:
        self.responses = [
            httpx.Response(200, json={"results": []}, headers={
                "Link": '</rest/api/search?start=10&limit=10>; rel="next"',
            }),
            httpx.Response(200, json={"results": []}),
        ]
        first = await self.reader.search("ambiente", None, 10, None)
        await self.reader.search("ambiente", None, 10, first["nextCursor"])
        self.assertEqual(self.requests[1].url.params["start"], "10")
        self.assertIn('text~"ambiente"', self.requests[1].url.params["cql"])

    async def test_untrusted_pagination_url_is_rejected(self) -> None:
        self.responses = [httpx.Response(200, json={
            "results": [], "_links": {"next": "https://other.invalid/?cursor=x"},
        })]
        with self.assertRaisesRegex(ValueError, "Destino"):
            await self.reader.spaces(25, None)
        self.assertEqual(len(self.requests), 1)

    async def test_cursor_cannot_override_cql(self) -> None:
        cursor = base64.urlsafe_b64encode(
            json.dumps({"scope": "x", "paging": {"cql": "type=blogpost"}}).encode()
        ).decode()
        with self.assertRaisesRegex(ValueError, "Cursor"):
            await self.reader.search("ambiente", None, 10, cursor)
        self.assertFalse(self.requests)

    async def test_get_page_returns_full_text_or_storage(self) -> None:
        body = "<h1>Guía</h1><p>" + "contenido " * 3000 + "</p>"
        response = {"id": "123", "title": "Guía", "spaceId": "1",
                    "body": {"storage": {"value": body}}}
        self.responses = [httpx.Response(200, json=response) for _ in range(2)]
        text = await self.reader.page("123", "text")
        storage = await self.reader.page("123", "storage")
        self.assertGreater(len(text["content"]), 24000)
        self.assertFalse(text["truncated"])
        self.assertEqual(storage["content"], body)
        self.assertEqual(self.requests[0].url.params["body-format"], "storage")

    async def test_children_are_not_fetched_recursively(self) -> None:
        self.responses = [httpx.Response(200, json={
            "results": [{"id": "124", "title": "Hija", "spaceId": "1"}],
        })]
        result = await self.reader.children("123", 25, None)
        self.assertEqual(result["results"][0]["id"], "124")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].url.path, "/wiki/api/v2/pages/123/children")

    async def test_rate_limit_retries_then_returns_results(self) -> None:
        self.responses = [
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(200, json={"results": []}),
        ]
        with patch("scripts.confluence_mcp.asyncio.sleep", new_callable=AsyncMock) as sleep:
            await self.reader.spaces(25, None)
        sleep.assert_awaited_once_with(3.0)
        self.assertEqual(len(self.requests), 2)

    async def test_long_rate_limit_fails_without_waiting(self) -> None:
        self.responses = [httpx.Response(429, headers={"Retry-After": "120"})]
        with self.assertRaisesRegex(ValueError, "120 segundos"):
            await self.reader.spaces(25, None)

    async def test_auth_failure_is_not_retried_or_hidden(self) -> None:
        self.responses = [httpx.Response(403)]
        with self.assertRaisesRegex(ValueError, "HTTP 403"):
            await self.reader.spaces(25, None)
        self.assertEqual(len(self.requests), 1)

    async def test_concurrent_requests_respect_limit(self) -> None:
        active = maximum = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.001)
            active -= 1
            return httpx.Response(200, json={"results": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            reader = ConfluenceReader("https://example.com", http)
            await asyncio.gather(*(reader.spaces(25, None) for _ in range(12)))
        self.assertLessEqual(maximum, 5)

    async def test_tool_schemas_expose_limits_and_pagination_not_context(self) -> None:
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        self.assertEqual(set(tools), {
            "confluence_list_spaces", "confluence_search_pages",
            "confluence_get_page", "confluence_get_page_children",
        })
        search = tools["confluence_search_pages"]
        properties = search.inputSchema["properties"]
        self.assertNotIn("ctx", properties)
        self.assertIn("spaceKeys", properties)
        self.assertIn("cursor", properties)
        self.assertEqual(properties["limit"]["maximum"], 100)
        self.assertTrue(search.annotations.readOnlyHint)
