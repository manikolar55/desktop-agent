"""Document creation workflow — text and PDF."""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


def draft_document(params: dict) -> str:
    title = params.get("title", "Document")
    content = params.get("content", "")
    format_ = params.get("format", "txt").lower()
    output_dir = Path(params.get("output_dir", "data/documents"))
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in title)[:60]
    filename = f"{safe_name}.{format_}"
    output_path = output_dir / filename

    if format_ == "pdf":
        return _write_pdf(title, content, output_path)
    else:
        output_path.write_text(content, encoding="utf-8")
        return f"Document saved: {output_path}"


def _write_pdf(title: str, content: str, path: Path) -> str:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.units import cm

        doc = SimpleDocTemplate(str(path), pagesize=A4)
        styles = getSampleStyleSheet()
        story = [
            Paragraph(title, styles["Title"]),
            Spacer(1, 0.5 * cm),
        ]
        for para in content.split("\n\n"):
            story.append(Paragraph(para.replace("\n", "<br/>"), styles["Normal"]))
            story.append(Spacer(1, 0.3 * cm))
        doc.build(story)
        return f"PDF saved: {path}"
    except Exception as exc:
        log.error("PDF generation failed: %s", exc)
        fallback = path.with_suffix(".txt")
        fallback.write_text(f"{title}\n\n{content}", encoding="utf-8")
        return f"PDF failed ({exc}); saved as text: {fallback}"
