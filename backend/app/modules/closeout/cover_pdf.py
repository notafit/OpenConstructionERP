# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Closeout cover-sheet + completeness summary PDF.

Renders the cover the brief asks for: a project header, project type and
build date, a traffic-light completeness summary, a per-slot table (slot,
status, evidence source, verified date) and a red gap list.

Security note (mirrors BUG-PDF01 / BUG-PDF02 in ``boq/pdf_export.py`` and
``daily_diary/pdf_export.py``): ReportLab's ``Paragraph`` parses a subset of
HTML, so every string that originates outside the application (project name,
slot titles, evidence labels) is escaped with ``html.escape`` via
:func:`_safe_para` before it reaches the parser. A payload like
``<font color="white">x</font>`` therefore renders inert.
"""

from __future__ import annotations

import html
import io
from datetime import UTC, datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.pdf_branding import branded_doc_metadata, branded_header_logo, branded_letterhead
from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, pdf_style_for_text, register_pdf_fonts

# Register the bundled Unicode (DejaVu) faces so Cyrillic / Greek / accented
# Latin text renders as glyphs rather than tofu boxes. Idempotent and safe.
register_pdf_fonts()

PAGE_WIDTH, PAGE_HEIGHT = A4
USABLE_WIDTH = PAGE_WIDTH - 40 * mm

# Traffic-light colours for the completeness band.
_GREEN = colors.HexColor("#15803d")
_AMBER = colors.HexColor("#b45309")
_RED = colors.HexColor("#b91c1c")
_GREY = colors.HexColor("#475569")
_HEADER_BG = colors.HexColor("#0f172a")
_ROW_ALT = colors.HexColor("#f1f5f9")


def _safe_para(text: Any, style: ParagraphStyle) -> Paragraph:
    """Construct a ``Paragraph`` from possibly-untrusted input (HTML-escaped).

    The style is also faced for the text it will draw. Every paragraph in this
    document goes through here, and the free text in it is whatever the parties
    are called: a project name, a slot title, an evidence reference. The
    bundled face has no Han glyph, so without this a Chinese project name is
    drawn as empty boxes and the codepoints are gone. The choice is per string,
    so text the base face can already draw is returned on the same style and
    the existing output does not move.
    """
    if text is None:
        rendered = ""
    elif isinstance(text, str):
        rendered = text
    else:
        rendered = str(text)
    return Paragraph(html.escape(rendered, quote=True), pdf_style_for_text(style, rendered))


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "CoTitle",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=20,
            # Normal's 12pt leading under a 20pt face drew the project name
            # through the lower half of the title.
            leading=24,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "CoSubtitle",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=11,
            textColor=_GREY,
            spaceAfter=2,
        ),
        "section": ParagraphStyle(
            "CoSection",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=13,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=10,
            spaceAfter=6,
        ),
        "cell": ParagraphStyle(
            "CoCell",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=9,
            textColor=colors.HexColor("#1e293b"),
            alignment=TA_LEFT,
        ),
        "cell_head": ParagraphStyle(
            "CoCellHead",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=9,
            textColor=colors.white,
            alignment=TA_LEFT,
        ),
        "gap": ParagraphStyle(
            "CoGap",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=10,
            textColor=_RED,
            spaceAfter=2,
        ),
        "banner": ParagraphStyle(
            "CoBanner",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=14,
            textColor=colors.white,
        ),
    }


_STATUS_LABELS = {
    "empty": "Empty",
    "bound": "Bound",
    "verified": "Verified",
}


def _completeness_colour(pct: int, ready: bool) -> colors.Color:
    if ready:
        return _GREEN
    if pct >= 50:
        return _AMBER
    return _RED


def render_cover_pdf(summary: dict[str, Any]) -> bytes:
    """Render the cover + completeness summary PDF for a closeout package.

    Args:
        summary: A plain dict (no ORM access) with keys:
            project_name, project_type, title, completeness_pct (int),
            required_slot_count, delivered_slot_count, ready (bool),
            gaps (list[str]), slots (list of {title, status, evidence,
            verified_at}), built_at (iso str | None).

    Returns:
        PDF file bytes.
    """
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="Closeout package",
        **branded_doc_metadata(),
    )

    pct = int(summary.get("completeness_pct", 0) or 0)
    ready = bool(summary.get("ready", False))
    built_at = summary.get("built_at") or datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    story: list[Any] = []
    story.append(_safe_para(summary.get("title") or "Digital handover & closeout package", styles["title"]))
    story.append(_safe_para(summary.get("project_name") or "Project", styles["subtitle"]))
    story.append(
        _safe_para(
            f"Project type: {summary.get('project_type', '-')}   |   Built: {built_at}",
            styles["subtitle"],
        )
    )
    story.append(Spacer(1, 8 * mm))

    # ── Traffic-light completeness band ──────────────────────────────────
    band_colour = _completeness_colour(pct, ready)
    if ready:
        band_text = f"READY - {pct}% complete - all required items verified"
    else:
        missing = len(summary.get("gaps", []) or [])
        band_text = f"{pct}% complete - {missing} required item(s) outstanding"
    band = Table([[_safe_para(band_text, styles["banner"])]], colWidths=[USABLE_WIDTH])
    band.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), band_colour),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    story.append(band)
    story.append(Spacer(1, 4 * mm))
    story.append(
        _safe_para(
            f"Required items: {summary.get('required_slot_count', 0)}   "
            f"Delivered: {summary.get('delivered_slot_count', 0)}",
            styles["subtitle"],
        )
    )

    # ── Per-slot table ───────────────────────────────────────────────────
    story.append(_safe_para("Checklist", styles["section"]))
    header = [
        _safe_para("Item", styles["cell_head"]),
        _safe_para("Status", styles["cell_head"]),
        _safe_para("Evidence", styles["cell_head"]),
        _safe_para("Verified", styles["cell_head"]),
    ]
    rows: list[list[Any]] = [header]
    for slot in summary.get("slots", []) or []:
        status = str(slot.get("status", "empty"))
        rows.append(
            [
                _safe_para(slot.get("title", ""), styles["cell"]),
                _safe_para(_STATUS_LABELS.get(status, status), styles["cell"]),
                _safe_para(slot.get("evidence") or "-", styles["cell"]),
                _safe_para(slot.get("verified_at") or "-", styles["cell"]),
            ]
        )
    table = Table(
        rows,
        colWidths=[USABLE_WIDTH * 0.40, USABLE_WIDTH * 0.16, USABLE_WIDTH * 0.30, USABLE_WIDTH * 0.14],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)

    # ── Gap list ─────────────────────────────────────────────────────────
    gaps = summary.get("gaps", []) or []
    if gaps:
        story.append(_safe_para("Outstanding required items", styles["section"]))
        for gap in gaps:
            story.append(_safe_para(f"- {gap}", styles["gap"]))

    # The frame pads 6pt on each side, so this is the width a flowable can use.
    letterhead = branded_letterhead(doc.width - 12, doc_type="closeout_cover")
    if letterhead is not None:
        story.insert(0, letterhead)

    def _first_page(canvas: Any, page_doc: Any) -> None:
        # A letterhead already carries the logo; the header copy would print it twice.
        if letterhead is None:
            branded_header_logo(canvas, page_doc)

    doc.build(story, onFirstPage=_first_page, onLaterPages=branded_header_logo)
    return buf.getvalue()
