"""Extract readable content and structure from Confluence page bodies."""

from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from .config import EvaluationError


@dataclass
class ExtractedDocument:
    text: str
    spelling_text: str
    headings: list[dict[str, Any]]
    list_count: int
    table_count: int
    code_block_count: int
    links: list[str]

class StorageParser(HTMLParser):
    _BLOCK_TAGS = {
        "p",
        "div",
        "br",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.spelling_parts: list[str] = []
        self.headings: list[dict[str, Any]] = []
        self.links: list[str] = []
        self.list_count = 0
        self.table_count = 0
        self.code_block_count = 0
        self._active_heading_level: int | None = None
        self._active_heading_parts: list[str] = []
        self._skip_spelling_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"ul", "ol"}:
            self.list_count += 1
        elif tag == "table":
            self.table_count += 1
        elif tag in {"pre", "code"}:
            self.code_block_count += 1
            self._skip_spelling_depth += 1
        elif tag in {"script", "style"}:
            self._skip_spelling_depth += 1

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._active_heading_level = int(tag[1])
            self._active_heading_parts = []

        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href.strip())

        if tag in self._BLOCK_TAGS:
            self.text_parts.append("\n")
            if self._skip_spelling_depth == 0:
                self.spelling_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            heading = " ".join("".join(self._active_heading_parts).split())
            self.headings.append({"level": int(tag[1]), "text": heading})
            self._active_heading_level = None
            self._active_heading_parts = []

        if tag in {"pre", "code", "script", "style"} and self._skip_spelling_depth:
            self._skip_spelling_depth -= 1

        if tag in self._BLOCK_TAGS:
            self.text_parts.append("\n")
            if self._skip_spelling_depth == 0:
                self.spelling_parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)
        if self._skip_spelling_depth == 0:
            self.spelling_parts.append(data)
        if self._active_heading_level is not None:
            self._active_heading_parts.append(data)

def extract_document(storage_value: str) -> ExtractedDocument:
    parser = StorageParser()
    parser.feed(storage_value)
    parser.close()
    return ExtractedDocument(
        text=" ".join("".join(parser.text_parts).split()),
        spelling_text=" ".join("".join(parser.spelling_parts).split()),
        headings=parser.headings,
        list_count=parser.list_count,
        table_count=parser.table_count,
        code_block_count=parser.code_block_count,
        links=parser.links,
    )

def storage_value(item: dict[str, Any]) -> str:
    body = item.get("body")
    if not isinstance(body, dict):
        return ""
    storage = body.get("storage")
    if isinstance(storage, dict) and isinstance(storage.get("value"), str):
        return storage["value"]
    if isinstance(body.get("value"), str):
        return body["value"]
    return ""

def _adf_plain_text(node: dict[str, Any]) -> str:
    if node.get("type") == "text":
        value = node.get("text")
        return value if isinstance(value, str) else ""
    content = node.get("content")
    if not isinstance(content, list):
        return ""
    return "".join(
        _adf_plain_text(child) for child in content if isinstance(child, dict)
    )

def extract_atlas_doc_format(value: Any) -> ExtractedDocument:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise EvaluationError("Confluence devolvió Atlas Doc Format inválido.") from error
    if not isinstance(value, dict):
        raise EvaluationError("Confluence devolvió Atlas Doc Format con formato inválido.")

    text_parts: list[str] = []
    spelling_parts: list[str] = []
    headings: list[dict[str, Any]] = []
    links: list[str] = []
    list_count = 0
    table_count = 0
    code_block_count = 0
    block_nodes = {
        "blockquote",
        "codeBlock",
        "heading",
        "listItem",
        "mediaSingle",
        "paragraph",
        "tableCell",
        "tableHeader",
        "tableRow",
    }

    def visit(node: dict[str, Any], in_code_block: bool = False) -> None:
        nonlocal list_count, table_count, code_block_count
        node_type = node.get("type")
        is_code_block = in_code_block or node_type == "codeBlock"
        if node_type in block_nodes:
            text_parts.append("\n")
            if not in_code_block:
                spelling_parts.append("\n")
        if node_type in {"bulletList", "orderedList"}:
            list_count += 1
        elif node_type == "table":
            table_count += 1
        elif node_type == "codeBlock":
            code_block_count += 1
        elif node_type == "heading":
            attrs = node.get("attrs")
            level = attrs.get("level") if isinstance(attrs, dict) else None
            if isinstance(level, int) and not isinstance(level, bool):
                headings.append(
                    {"level": level, "text": _adf_plain_text(node).strip()}
                )
        elif node_type == "text":
            text = node.get("text")
            if isinstance(text, str):
                text_parts.append(text)
                if not is_code_block:
                    spelling_parts.append(text)
                marks = node.get("marks")
                if isinstance(marks, list):
                    for mark in marks:
                        if not isinstance(mark, dict) or mark.get("type") != "link":
                            continue
                        attrs = mark.get("attrs")
                        href = attrs.get("href") if isinstance(attrs, dict) else None
                        if isinstance(href, str) and href.strip():
                            links.append(href.strip())
        elif node_type == "inlineCard":
            attrs = node.get("attrs")
            url = attrs.get("url") if isinstance(attrs, dict) else None
            if isinstance(url, str) and url.strip():
                links.append(url.strip())

        content = node.get("content")
        if isinstance(content, list):
            for child in content:
                if isinstance(child, dict):
                    visit(child, is_code_block)
        if node_type in block_nodes:
            text_parts.append("\n")
            if not in_code_block:
                spelling_parts.append("\n")

    visit(value)
    return ExtractedDocument(
        text=" ".join("".join(text_parts).split()),
        spelling_text=" ".join("".join(spelling_parts).split()),
        headings=headings,
        list_count=list_count,
        table_count=table_count,
        code_block_count=code_block_count,
        links=links,
    )

def extract_item_document(item: dict[str, Any]) -> ExtractedDocument:
    storage = storage_value(item)
    if storage.strip():
        return extract_document(storage)
    body = item.get("body")
    atlas_doc_format = body.get("atlas_doc_format") if isinstance(body, dict) else None
    if isinstance(atlas_doc_format, dict):
        return extract_atlas_doc_format(atlas_doc_format.get("value", atlas_doc_format))
    return extract_document("")
