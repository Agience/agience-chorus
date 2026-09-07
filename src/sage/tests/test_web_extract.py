"""Unit tests for Sage's web_extract (the web_retrieve tool's text-extraction core)."""
from web_extract import html_to_text, looks_like_html


def test_drops_boilerplate_keeps_content():
    html = ("<html><head><title>x</title><style>body{color:red}</style></head><body>"
            "<nav>menu links</nav><h1>Main Title</h1><p>Hello <b>world</b>.</p>"
            "<script>evil()</script><footer>copyright</footer>"
            "<p>Second paragraph here.</p></body></html>")
    out = html_to_text(html)
    assert "Main Title" in out
    assert "Hello world." in out
    assert "Second paragraph here." in out
    for junk in ("evil()", "menu links", "color:red", "copyright"):
        assert junk not in out


def test_paragraph_breaks_and_whitespace_collapse():
    out = html_to_text("<p>one</p><p>two</p><div>three</div>")
    assert out == "one\ntwo\nthree" or out.replace("\n\n", "\n") == "one\ntwo\nthree"
    assert "   " not in html_to_text("<p>a     b</p>")


def test_empty_and_malformed_are_safe():
    assert html_to_text("") == ""
    assert html_to_text("<p>ok<unclosed") .startswith("ok")
    assert html_to_text("plain text no tags") == "plain text no tags"


def test_looks_like_html():
    assert looks_like_html("text/html; charset=utf-8", "")
    assert looks_like_html("", "<!doctype html>")
    assert not looks_like_html("text/plain", "just text")
    assert not looks_like_html("application/json", '{"a":1}')
