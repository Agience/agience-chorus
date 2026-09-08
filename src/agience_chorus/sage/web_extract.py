"""HTML -> clean text extraction for Sage's web_retrieve tool.

Pure stdlib (html.parser + re), no Chorus deps — so it is importable and unit-testable on its own.
Drops boilerplate (script/style/nav/footer/head) and keeps readable content with sane line breaks.
Not a full readability engine; a dependency-free, good-enough extractor for grounding a fetched page.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "head", "nav", "footer", "svg", "template", "aside"}
    _BREAK = {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section",
              "article", "ul", "ol", "table", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BREAK:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self._chunks.append(data)


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:
        pass
    text = "".join(p._chunks)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text)
    return text.strip()


def looks_like_html(content_type: str, body: str) -> bool:
    return "html" in (content_type or "").lower() or body.lstrip()[:1] == "<"


__all__ = ["html_to_text", "looks_like_html"]
