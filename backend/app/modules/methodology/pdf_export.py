# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PDF report generation for methodology-driven cost estimates.

Renders the output of :meth:`MethodologyService.compute_estimate` as a
professional, client-facing PDF:

- Cover page: project name, methodology name, the markup-cascade summary
  (direct cost / total markup / grand total), date and currency.
- Cascade table: the resolved direct-cost base, every ordered markup step
  (rate, amount, running total) and the grand total.

It mirrors the BOQ PDF exporter (:mod:`app.modules.boq.pdf_export`): same
A4 layout, same bundled DejaVu Unicode faces, same locale-aware money
formatting, and the same ``_safe_para`` escaping so a malicious methodology
name / step label can neither crash ReportLab's paraparser nor smuggle
markup into the printed output (BUG-PDF01 / BUG-PDF02).

All money arrives from the compute layer as decimal strings (never blended
across currencies); this module coerces them to ``Decimal`` for display and
never does float arithmetic on monetary values.
"""

import html
import io
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.core.pdf_branding import branded_cover_brand, branded_doc_metadata, branded_header_logo
from app.core.pdf_fonts import (
    BODY_FONT,
    BOLD_FONT,
    pdf_fit_line,
    pdf_fitted_style,
    pdf_font_for_text,
    pdf_room_beside,
    pdf_style_for_text,
    register_pdf_fonts,
)

# Register the bundled Unicode (DejaVu) faces with reportlab. Idempotent and
# safe at import time because reportlab is imported at module level here.
register_pdf_fonts()

# Page dimensions
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_LEFT = 20 * mm
MARGIN_RIGHT = 20 * mm
MARGIN_TOP = 25 * mm
MARGIN_BOTTOM = 20 * mm
USABLE_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

# Cascade table columns: Step | Category | Rate | Base | Amount | Running total
COL_STEP = USABLE_WIDTH - 30 * mm - 22 * mm - 30 * mm - 30 * mm - 32 * mm
COL_CATEGORY = 30 * mm
COL_RATE = 22 * mm
COL_BASE = 30 * mm
COL_AMOUNT = 30 * mm
COL_RUNNING = 32 * mm
TABLE_COL_WIDTHS = [COL_STEP, COL_CATEGORY, COL_RATE, COL_BASE, COL_AMOUNT, COL_RUNNING]


def _to_decimal(value: Any) -> Decimal:
    """Coerce a money / rate value (string, Decimal, number) to a finite Decimal.

    The compute layer emits decimal strings; non-finite or unparseable input
    collapses to ``0`` so one bad value never breaks a render.
    """
    if value is None or value == "":
        return Decimal(0)
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return Decimal(0)
    return d if d.is_finite() else Decimal(0)


def _fmt(value: Any, decimals: int = 2, currency: str = "") -> str:
    """Format a money value with thousands separator and fixed decimals.

    Locale-aware, matching the BOQ exporter:
    - EUR (German/DACH): 1.234,56  (dot=thousands, comma=decimal)
    - CHF (Swiss):       1'234.56  (apostrophe=thousands, dot=decimal)
    - everything else:   1,234.56  (comma=thousands, dot=decimal)

    Done on a Decimal (quantized) so large totals never drift through float.
    """
    d = _to_decimal(value)
    quant = Decimal(1).scaleb(-decimals) if decimals > 0 else Decimal(1)
    try:
        d = d.quantize(quant)
    except InvalidOperation:
        pass
    raw = f"{d:,.{decimals}f}"
    cur = (currency or "").upper()
    if cur == "EUR":
        return raw.replace(",", "THOU").replace(".", ",").replace("THOU", ".")
    if cur == "CHF":
        return raw.replace(",", "'")
    return raw


def _fmt_currency(value: Any, currency: str, decimals: int = 2) -> str:
    """Format a monetary amount with the currency code appended (empty-safe)."""
    formatted = _fmt(value, decimals, currency)
    return f"{formatted} {currency}".rstrip()


def _safe_para(text: Any, style: ParagraphStyle) -> "Paragraph":
    """Construct a ``Paragraph`` from possibly-untrusted user input.

    HTML metacharacters in ``text`` are escaped via ``html.escape`` so
    ReportLab's paraparser sees inert characters, not markup (a methodology
    name like ``<font color="white">x</font>`` would otherwise render styled,
    and ``<img onerror=...>`` would crash the parser - BUG-PDF01). Internal
    labels that legitimately use ReportLab inline markup (``<b>...</b>``)
    construct ``Paragraph`` directly - that text is checked into source.

    The style is also faced here for the script the text is written in, since a
    style carries its face in ``fontName`` and this module builds its styles
    once. The face is chosen from the raw string rather than the escaped one:
    escaping only ever adds ASCII, so the two cannot disagree about which face
    is needed, and asking the raw string keeps the question about what the user
    wrote. Every cell in this document that a party fills goes through here,
    with one exception noted at the ``prepared_by`` line.
    """
    if text is None:
        rendered = ""
    elif isinstance(text, str):
        rendered = text
    else:
        rendered = str(text)
    return Paragraph(html.escape(rendered, quote=True), pdf_style_for_text(style, rendered))


def _build_styles() -> dict[str, ParagraphStyle]:
    """Build the set of paragraph styles used throughout the PDF."""
    base = getSampleStyleSheet()

    return {
        "brand": ParagraphStyle(
            "Brand",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=22,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#1a1a2e"),
            spaceAfter=6 * mm,
        ),
        "title": ParagraphStyle(
            "CoverTitle",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=18,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#16213e"),
            spaceAfter=4 * mm,
        ),
        "subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#333333"),
            spaceAfter=2 * mm,
        ),
        "info_label": ParagraphStyle(
            "InfoLabel",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=10,
            textColor=colors.HexColor("#666666"),
            alignment=TA_LEFT,
        ),
        "info_value": ParagraphStyle(
            "InfoValue",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=10,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_LEFT,
        ),
        "summary_label": ParagraphStyle(
            "SummaryLabel",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=11,
            textColor=colors.HexColor("#333333"),
            alignment=TA_LEFT,
        ),
        "summary_value": ParagraphStyle(
            "SummaryValue",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=11,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_RIGHT,
        ),
        "summary_total_label": ParagraphStyle(
            "SummaryTotalLabel",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=12,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_LEFT,
        ),
        "summary_total_value": ParagraphStyle(
            "SummaryTotalValue",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=12,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_RIGHT,
        ),
        "section_header": ParagraphStyle(
            "SectionHeader",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=9,
            textColor=colors.HexColor("#1a1a2e"),
        ),
        "cell": ParagraphStyle(
            "Cell",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=8,
            textColor=colors.HexColor("#333333"),
            leading=10,
        ),
        "cell_right": ParagraphStyle(
            "CellRight",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=8,
            textColor=colors.HexColor("#333333"),
            alignment=TA_RIGHT,
            leading=10,
        ),
        "cell_bold_right": ParagraphStyle(
            "CellBoldRight",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=8,
            textColor=colors.HexColor("#333333"),
            alignment=TA_RIGHT,
            leading=10,
        ),
        # The header row of the step table and of the appendix. A TableStyle
        # TEXTCOLOR cannot reach a cell that holds a Paragraph, so the colour
        # of a header has to live on the header's own style. It did not, and
        # "Step", "Category", "Key" and "Type" were drawn #1a1a2e on the
        # #1a1a2e fill they were standing on.
        #
        # Sizes are the ones these rows already rendered at, 9pt on the left
        # and 8pt on the right to match their columns. The table style also
        # carried a FONTSIZE of 9 for the whole row, equally unable to act.
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=9,
            textColor=colors.white,
        ),
        "table_header_right": ParagraphStyle(
            "TableHeaderRight",
            parent=base["Normal"],
            fontName=BOLD_FONT,
            fontSize=8,
            textColor=colors.white,
            alignment=TA_RIGHT,
            leading=10,
        ),
        "footer": ParagraphStyle(
            "Footer",
            parent=base["Normal"],
            fontName=BODY_FONT,
            fontSize=7,
            textColor=colors.HexColor("#999999"),
        ),
    }


def _make_header_footer(
    project_name: str,
    methodology_name: str,
    generated_date: str,
) -> tuple[Any, Any]:
    """Return (header_func, footer_func) for the cascade table pages.

    These callables follow the reportlab PageTemplate onPage signature:
    ``func(canvas, doc)``.
    """

    def _header(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#666666"))
        # A plain hyphen separator (never an em dash) per the project text rule.
        text = f"{project_name}  -  {methodology_name}"
        # Both names are party-supplied and may contain non-Latin text that needs
        # shaping (Thai tone marks, Devanagari reordering). Paragraph is the only
        # route through which reportlab's shaper acts; canvas.drawString drops its
        # shaping argument silently without rlbidi.
        header_style = ParagraphStyle(
            "_methHeader",
            fontName=BODY_FONT,
            fontSize=8,
            leading=8,
            textColor=colors.HexColor("#666666"),
        )
        p = Paragraph(html.escape(text, quote=True), pdf_style_for_text(header_style, text))
        pw, ph = p.wrapOn(canvas, PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT, 20)
        p.drawOn(canvas, MARGIN_LEFT, PAGE_HEIGHT - 15 * mm - ph + 8 * 0.22)
        canvas.setStrokeColor(colors.HexColor("#cccccc"))
        canvas.setLineWidth(0.5)
        line_y = PAGE_HEIGHT - 17 * mm
        canvas.line(MARGIN_LEFT, line_y, PAGE_WIDTH - MARGIN_RIGHT, line_y)
        canvas.restoreState()
        # White-label logo (if configured) top-right, clearing the header title.
        branded_header_logo(canvas, doc)

    def _footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#999999"))
        if getattr(doc, "page_count", 0) > 0:
            page_text = f"Page {doc.page} of {doc.page_count}"
        else:
            page_text = f"Page {doc.page}"
        # The brand is white-label configurable and can be in any script;
        # Paragraph is needed so the shaper can act on it.
        footer_style = ParagraphStyle(
            "_methFooter",
            fontName=BODY_FONT,
            fontSize=7,
            leading=7,
            textColor=colors.HexColor("#999999"),
        )
        # Fitted onto one line in the room beside the page number: the brand is
        # the firm's legal name and can reach the number, and this paragraph is
        # anchored by its top, so a wrapped one would run off the bottom edge.
        brand_line, _brand_face, brand_size = pdf_fit_line(
            branded_cover_brand(),
            pdf_room_beside(PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT, page_text),
            suffix=f"  |  Generated: {generated_date}",
            base=BODY_FONT,
        )
        p = Paragraph(html.escape(brand_line, quote=True), pdf_fitted_style(footer_style, brand_line, brand_size))
        pw, ph = p.wrapOn(canvas, PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT, 20)
        p.drawOn(canvas, MARGIN_LEFT, 10 * mm - ph + 7 * 0.22)
        # Page counter is always ASCII, safe as bare drawString.
        canvas.setFont(pdf_font_for_text(page_text, base=BODY_FONT), 7)
        canvas.drawRightString(PAGE_WIDTH - MARGIN_RIGHT, 10 * mm, page_text)
        canvas.restoreState()

    return _header, _footer


class _NumberedDocTemplate(BaseDocTemplate):
    """DocTemplate that tracks total page count for 'Page X of Y' footers."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.page_count = 0

    def afterPage(self) -> None:  # noqa: N802
        """Called after each page is completed."""
        self.page_count = max(self.page_count, self.page)


def _build_cover_page(
    data: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    """Build the cover-page flowables from the export data dict."""
    elements: list[Any] = []
    currency = data.get("currency", "") or ""
    decimals = int(data.get("decimals", 2))

    elements.append(Spacer(1, 30 * mm))
    elements.append(_safe_para(branded_cover_brand(), styles["brand"]))
    elements.append(Spacer(1, 10 * mm))

    # Decorative line
    line_table = Table([[""]], colWidths=[120 * mm], rowHeights=[0.8 * mm])
    line_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1a1a2e")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    line_wrapper = Table([[line_table]], colWidths=[USABLE_WIDTH])
    line_wrapper.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    elements.append(line_wrapper)
    elements.append(Spacer(1, 4 * mm))

    elements.append(Paragraph("COST ESTIMATE", styles["title"]))
    elements.append(Spacer(1, 2 * mm))
    elements.append(line_wrapper)
    elements.append(Spacer(1, 12 * mm))

    # Project / methodology info. Labels are first-party constants; values come
    # from project / methodology records and may contain HTML - escape the
    # dynamic side only.
    info_rows = [
        ("Project:", data.get("project_name", "")),
        ("Methodology:", data.get("methodology_name", "")),
        ("Method ID:", data.get("methodology_slug", "")),
        ("Date:", datetime.now(tz=UTC).strftime("%d.%m.%Y")),
        ("Currency:", currency or "-"),
    ]
    info_table_data = [
        [Paragraph(label, styles["info_label"]), _safe_para(value, styles["info_value"])] for label, value in info_rows
    ]
    info_table = Table(info_table_data, colWidths=[35 * mm, 95 * mm], hAlign="CENTER")
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1 * mm),
            ]
        )
    )
    elements.append(info_table)
    elements.append(Spacer(1, 12 * mm))

    # Separator
    sep_table = Table([[""]], colWidths=[130 * mm], rowHeights=[0.3 * mm])
    sep_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#cccccc")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    sep_wrapper = Table([[sep_table]], colWidths=[USABLE_WIDTH])
    sep_wrapper.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    elements.append(sep_wrapper)
    elements.append(Spacer(1, 6 * mm))

    elements.append(Paragraph("SUMMARY", styles["title"]))
    elements.append(Spacer(1, 4 * mm))

    summary_rows = [
        ("Direct Cost:", _fmt_currency(data.get("direct_total"), currency, decimals), False),
        ("Total Markup:", _fmt_currency(data.get("markup_total"), currency, decimals), False),
        ("Grand Total:", _fmt_currency(data.get("grand_total"), currency, decimals), True),
    ]
    summary_table_data = []
    for label, value, is_total in summary_rows:
        lbl_style = styles["summary_total_label"] if is_total else styles["summary_label"]
        val_style = styles["summary_total_value"] if is_total else styles["summary_value"]
        summary_table_data.append([Paragraph(label, lbl_style), Paragraph(value, val_style)])

    summary_table = Table(summary_table_data, colWidths=[60 * mm, 70 * mm], hAlign="CENTER")
    summary_style_commands: list[Any] = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]
    last_row = len(summary_rows) - 1
    summary_style_commands.append(("LINEABOVE", (0, last_row), (-1, last_row), 1, colors.HexColor("#1a1a2e")))
    summary_table.setStyle(TableStyle(summary_style_commands))
    elements.append(summary_table)

    elements.append(Spacer(1, 10 * mm))
    elements.append(sep_wrapper)
    elements.append(Spacer(1, 6 * mm))

    prepared_by = data.get("prepared_by", "")
    if prepared_by:
        # ``prepared_by`` is user-supplied; escape before splicing into markup.
        elements.append(
            Paragraph(
                "Prepared by: " + html.escape(str(prepared_by), quote=True),
                # The exception to the rule above: this is the one place user
                # text takes the direct-Paragraph path, which the docstring on
                # _safe_para reserves for strings checked into source. So it
                # needs facing of its own, and facing the funnel alone leaves
                # exactly this line boxing. Faced on the value rather than the
                # whole line because the label is ASCII, so both give the same
                # answer and this keeps the question about what the user wrote.
                pdf_style_for_text(styles["subtitle"], str(prepared_by)),
            )
        )

    return elements


def _build_cascade_table(
    data: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    """Build the cascade breakdown table flowables from the export data dict."""
    elements: list[Any] = []
    currency = data.get("currency", "") or ""
    decimals = int(data.get("decimals", 2))

    def _fm(value: Any) -> str:
        return _fmt(value, decimals, currency)

    elements.append(
        Paragraph(
            f"<b>Markup cascade</b> ({currency})" if currency else "<b>Markup cascade</b>",
            styles["section_header"],
        )
    )
    elements.append(Spacer(1, 3 * mm))

    header_row = [
        Paragraph("<b>Step</b>", styles["table_header"]),
        Paragraph("<b>Category</b>", styles["table_header"]),
        Paragraph("<b>Rate</b>", styles["table_header_right"]),
        Paragraph("<b>Base</b>", styles["table_header_right"]),
        Paragraph("<b>Amount</b>", styles["table_header_right"]),
        Paragraph("<b>Running total</b>", styles["table_header_right"]),
    ]
    table_data: list[list[Any]] = [header_row]
    row_styles: list[tuple[int, str]] = []
    row_idx = 1

    # Direct-cost opening row.
    table_data.append(
        [
            Paragraph("<b>Direct cost</b>", styles["section_header"]),
            "",
            "",
            "",
            "",
            Paragraph(f"<b>{_fm(data.get('direct_total'))}</b>", styles["cell_bold_right"]),
        ]
    )
    row_styles.append((row_idx, "direct"))
    row_idx += 1

    steps = data.get("steps", []) or []
    for step in steps:
        kind = step.get("kind", "percentage")
        rate_val = _to_decimal(step.get("rate"))
        rate_text = f"{_fmt(rate_val, 2)}%" if kind == "percentage" else "-"
        table_data.append(
            [
                _safe_para(step.get("label") or step.get("key", ""), styles["cell"]),
                _safe_para(step.get("category", ""), styles["cell"]),
                Paragraph(rate_text, styles["cell_right"]),
                Paragraph(_fm(step.get("base_amount")), styles["cell_right"]),
                Paragraph(_fm(step.get("amount")), styles["cell_right"]),
                Paragraph(_fm(step.get("running_total")), styles["cell_right"]),
            ]
        )
        row_styles.append((row_idx, "tax" if step.get("category") == "tax" else "step"))
        row_idx += 1

    # Grand-total row.
    table_data.append(
        [
            Paragraph("<b>Grand total</b>", styles["section_header"]),
            "",
            "",
            "",
            "",
            Paragraph(f"<b>{_fm(data.get('grand_total'))}</b>", styles["cell_bold_right"]),
        ]
    )
    row_styles.append((row_idx, "grand_total"))
    row_idx += 1

    table = Table(table_data, colWidths=TABLE_COL_WIDTHS, repeatRows=1)
    style_commands: list[Any] = [
        # The fill only: every cell here is a Paragraph and carries its own
        # face, size and colour, so a TEXTCOLOR, FONTNAME or FONTSIZE command
        # would read as authoritative and change nothing on the page.
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#1a1a2e")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f8f8")]),
    ]
    for ri, row_type in row_styles:
        if row_type == "direct":
            style_commands.append(("BACKGROUND", (0, ri), (-1, ri), colors.HexColor("#f0f0f5")))
        elif row_type == "tax":
            style_commands.append(("BACKGROUND", (0, ri), (-1, ri), colors.HexColor("#eef2fb")))
        elif row_type == "grand_total":
            style_commands.append(("LINEABOVE", (0, ri), (-1, ri), 1.5, colors.HexColor("#1a1a2e")))
            style_commands.append(("BACKGROUND", (0, ri), (-1, ri), colors.HexColor("#e8e8ee")))
    table.setStyle(TableStyle(style_commands))
    elements.append(table)

    # Resolved bases / composites appendix - the figures the cascade applied to,
    # so the deliverable is auditable.
    bases = data.get("bases", {}) or {}
    composites = data.get("composites", {}) or {}
    if bases or composites:
        elements.append(Spacer(1, 6 * mm))
        elements.append(Paragraph("<b>Resolved bases</b>", styles["section_header"]))
        elements.append(Spacer(1, 2 * mm))
        appendix_data: list[list[Any]] = [
            [
                Paragraph("<b>Key</b>", styles["table_header"]),
                Paragraph("<b>Type</b>", styles["table_header"]),
                Paragraph("<b>Amount</b>", styles["table_header_right"]),
            ]
        ]
        for key, amount in bases.items():
            appendix_data.append(
                [
                    _safe_para(key, styles["cell"]),
                    Paragraph("base", styles["cell"]),
                    Paragraph(_fm(amount), styles["cell_right"]),
                ]
            )
        for key, amount in composites.items():
            appendix_data.append(
                [
                    _safe_para(key, styles["cell"]),
                    Paragraph("composite", styles["cell"]),
                    Paragraph(_fm(amount), styles["cell_right"]),
                ]
            )
        appendix = Table(
            appendix_data,
            colWidths=[USABLE_WIDTH - 30 * mm - 35 * mm, 30 * mm, 35 * mm],
            repeatRows=1,
        )
        appendix.setStyle(
            TableStyle(
                [
                    # The fill only, for the same reason as the step table.
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#1a1a2e")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f8f8f8")],
                    ),
                ]
            )
        )
        elements.append(appendix)

    return elements


def _new_doc(buffer: io.BytesIO, data: dict[str, Any]) -> _NumberedDocTemplate:
    """Build a configured DocTemplate with origin metadata stamped."""
    methodology_name = str(data.get("methodology_name", "") or "Methodology")
    return _NumberedDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"Cost Estimate - {methodology_name}",
        author=branded_doc_metadata()["author"],
        subject="Methodology cost estimate",
        creator=branded_doc_metadata()["creator"],
        producer=branded_doc_metadata()["producer"],
        keywords=branded_doc_metadata()["keywords"],
    )


def generate_methodology_pdf(data: dict[str, Any]) -> bytes:
    """Generate a professional PDF cost estimate from a methodology compute.

    Args:
        data: The dict returned by
            :meth:`MethodologyService.build_export_data` - project / methodology
            identity, currency, decimals, the resolved bases / composites, the
            ordered cascade steps and the direct / markup / grand totals.

    Returns:
        PDF file contents as bytes.
    """
    styles = _build_styles()
    generated_date = datetime.now(tz=UTC).strftime("%d.%m.%Y")
    project_name = str(data.get("project_name", "") or "")
    methodology_name = str(data.get("methodology_name", "") or "")

    header_func, footer_func = _make_header_footer(project_name, methodology_name, generated_date)

    cover_frame = Frame(
        MARGIN_LEFT,
        MARGIN_BOTTOM,
        USABLE_WIDTH,
        PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM,
        id="cover",
    )
    table_frame = Frame(
        MARGIN_LEFT,
        MARGIN_BOTTOM + 5 * mm,
        USABLE_WIDTH,
        PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM - 12 * mm,
        id="table",
    )

    def _table_page_handler(canvas: Any, doc: Any) -> None:
        header_func(canvas, doc)
        footer_func(canvas, doc)

    cover_template = PageTemplate(id="cover", frames=[cover_frame])
    table_template = PageTemplate(id="table", frames=[table_frame], onPage=_table_page_handler)

    def _build_flowables() -> list[Any]:
        flowables: list[Any] = []
        flowables.extend(_build_cover_page(data, styles))
        flowables.append(NextPageTemplate("table"))
        flowables.append(PageBreak())
        flowables.extend(_build_cascade_table(data, styles))
        return flowables

    # Two-pass build: first pass counts pages, second renders 'Page X of Y'.
    buffer = io.BytesIO()
    doc = _new_doc(buffer, data)
    doc.addPageTemplates([cover_template, table_template])
    doc.build(_build_flowables())
    total_pages = doc.page_count

    buffer.seek(0)
    buffer.truncate()
    doc2 = _new_doc(buffer, data)
    doc2.page_count = total_pages
    doc2.addPageTemplates([cover_template, table_template])
    doc2.build(_build_flowables())

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
