"""Tests for HTML content extraction."""

from browser.page_inspector import extract_text_from_html, find_links, find_forms


class TestExtractText:
    def test_strips_tags(self):
        html = "<p>Hello <b>World</b></p>"
        assert "Hello" in extract_text_from_html(html)
        assert "<p>" not in extract_text_from_html(html)

    def test_removes_scripts(self):
        html = "<script>alert('xss')</script><p>Safe</p>"
        result = extract_text_from_html(html)
        assert "alert" not in result
        assert "Safe" in result

    def test_removes_styles(self):
        html = "<style>.a{color:red}</style><p>Content</p>"
        result = extract_text_from_html(html)
        assert "color" not in result
        assert "Content" in result

    def test_decodes_entities(self):
        html = "<p>AT&amp;T &lt;Corp&gt;</p>"
        result = extract_text_from_html(html)
        assert "AT&T" in result
        assert "<Corp>" in result


class TestFindLinks:
    def test_extracts_links(self):
        html = '<a href="https://example.com">Example</a>'
        links = find_links(html)
        assert any(l["href"] == "https://example.com" for l in links)
        assert any(l["text"] == "Example" for l in links)

    def test_relative_links_included(self):
        html = '<a href="/about">About</a>'
        links = find_links(html)
        assert any("/about" in l["href"] for l in links)


class TestFindForms:
    def test_extracts_form_fields(self):
        html = '<form action="/submit"><input name="email"/><input name="password"/></form>'
        forms = find_forms(html)
        assert len(forms) == 1
        assert "email" in forms[0]["fields"]
        assert "password" in forms[0]["fields"]
