"""Helpers for extracting readable content from HTML pages."""

from __future__ import annotations

import re


def extract_text_from_html(html: str) -> str:
    """Strip HTML tags and collapse whitespace to get readable text."""
    # Remove scripts and styles
    html = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", html, flags=re.S | re.I)
    # Remove tags
    html = re.sub(r"<[^>]+>", " ", html)
    # Decode common entities
    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    html = html.replace("&nbsp;", " ").replace("&quot;", '"').replace("&#39;", "'")
    # Collapse whitespace
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def find_links(html: str, base_url: str = "") -> list[dict]:
    """Extract href links and their anchor text from HTML."""
    pattern = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
    links = []
    for m in pattern.finditer(html):
        href, text = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if href.startswith("http") or href.startswith("/"):
            links.append({"href": href, "text": text[:100]})
    return links[:50]


def find_forms(html: str) -> list[dict]:
    """Extract form actions and input names from HTML."""
    forms = []
    for fm in re.finditer(r"<form[^>]*>(.*?)</form>", html, re.S | re.I):
        action = re.search(r'action=["\']([^"\']*)["\']', fm.group(0))
        inputs = re.findall(r'<input[^>]+name=["\']([^"\']+)["\']', fm.group(1), re.I)
        forms.append({"action": action.group(1) if action else "", "fields": inputs})
    return forms
