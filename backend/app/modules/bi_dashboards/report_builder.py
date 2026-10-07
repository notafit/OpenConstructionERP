# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PDF / CSV / XLSX report builder for the BI Dashboards module.

A single :class:`ReportBuilder` covers all output formats so the service
layer treats them uniformly. Files are written to a per-tenant tmpdir
(falling back to ``tempfile.gettempdir()``) and the absolute path is
returned to the caller for download streaming.

Why server-local files (not S3): some installs run without object
storage. The ``/reports/{report_id}/download`` endpoint streams from
disk; tenants on S3 patch the storage layer through a hook (out of
scope for v1).
"""

from __future__ import annotations

import csv
import logging
import os
import tempfile
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.core.pdf_branding import branded_doc_metadata, branded_letterhead
from app.core.pdf_fonts import (
    BODY_FONT,
    BOLD_FONT,
    pdf_table_available_width,
    pdf_table_column_widths,
    pdf_table_legible_columns,
    pdf_table_paragraph_rows,
    register_pdf_fonts,
)

logger = logging.getLogger(__name__)


# Words that are names rather than words, and look wrong in sentence case.
# A report is read by estimators and finance people who write AC and EAC, so
# "Ac by currency" reads as a typo where "AC by currency" reads as the column
# they asked for.
_HEADER_ACRONYMS: frozenset[str] = frozenset(
    {
        "ac",
        "bac",
        "boq",
        "co2",
        "copq",
        "cpi",
        "csv",
        "cv",
        "din",
        "dso",
        "eac",
        "etc",
        "ev",
        "fx",
        "gaeb",
        "hse",
        "id",
        "ids",
        "kpi",
        "nrm",
        "pdf",
        "po",
        "pv",
        "qa",
        "qc",
        "rfi",
        "rfq",
        "roi",
        "spi",
        "sv",
        "tcpi",
        "trir",
        "url",
        "vac",
        "vat",
        "wbs",
    },
)

#: Row keys that are structural rather than data. ``run_report`` flattens a
#: KPI's breakdown into ``breakdown__<key>`` columns; the prefix is a join
#: marker, not part of the reader's question.
_BREAKDOWN_PREFIX = "breakdown__"

#: The record a ``top_by`` KPI puts under each of its breakdown groups:
#: the winning row's label and the value it won on. ``run_report``
#: flattens a breakdown one level, so the group becomes the column and
#: this record becomes the whole cell. Named here rather than imported
#: from its producer (``kpi_spec._evaluate_top_by``) because that module
#: reaches the database and this one deliberately does not.
_LABEL_VALUE_RECORD: frozenset[str] = frozenset({"label", "value"})

#: The breakdown key a grouped KPI uses for rows that had no value in the
#: grouped column, and the text it is printed as. The key is reserved so
#: that a consumer can tell an absent group from a real one - a word could
#: not be told apart from a value like ``m3`` - and this module is the
#: consumer that turns it back into something a reader parses. Spelled out
#: rather than imported from ``kpi_spec.NULL_GROUP_KEY``, which declares
#: it, for the same reason as :data:`_LABEL_VALUE_RECORD`: that module
#: reaches the database and this one deliberately does not.
_NULL_GROUP_KEY = "__null__"
_NULL_GROUP_LABEL = "(not set)"


def humanize_column(name: str) -> str:
    """Turn a row key into a column heading a person can read.

    The row keys are an API shape - ``breakdown__ac_by_currency``,
    ``source_record_count`` - and printing them into a document is showing
    the reader the plumbing. They are also unreadable in a narrow column
    for a mechanical reason: a run with no spaces in it has nowhere to
    wrap, so ``breakdown__ac_by_currency`` gets chopped mid-word into
    six-character fragments, while ``Breakdown: AC by currency`` breaks
    between words.

    Only the heading changes. The row keys themselves are the JSON the
    report API returns and are left exactly as they are.

    Args:
        name: The row key.

    Returns:
        The heading to print.
    """
    label = name
    prefix = ""
    if label.startswith(_BREAKDOWN_PREFIX):
        prefix = "Breakdown: "
        label = label[len(_BREAKDOWN_PREFIX) :]
        if label == _NULL_GROUP_KEY:
            # A reserved key, not a word. Left to the word-splitting below
            # it reads "Null", which is the plumbing showing through again.
            return prefix + _NULL_GROUP_LABEL
    label = label.lstrip("_")
    if not label:
        return name
    words = [w for w in label.replace("_", " ").split(" ") if w]
    rendered: list[str] = []
    for index, word in enumerate(words):
        if word.lower() in _HEADER_ACRONYMS:
            rendered.append(word.upper())
        elif index == 0:
            rendered.append(word[:1].upper() + word[1:])
        else:
            rendered.append(word)
    return prefix + " ".join(rendered)


def _report_table(rows: list[dict[str, Any]]) -> list[list[str]]:
    """Turn report rows into a heading row and formatted cells.

    All three writers print the same report to a person, so all three ask
    for the table here rather than each assembling its own. They used not
    to, and the result was a fix that reached one format: the cell
    formatter was shared and the heading logic was not, so a report whose
    PDF read correctly still had ``breakdown__ac_by_currency`` across the
    top of its spreadsheet, and the CSV of the same run stringified
    through ``str`` and wrote ``{'EUR': Decimal('100000.00')}`` into a
    cell. Which of the three a reader gets is a setting on the report
    definition, so all three are documents and none of them is the
    machine's copy - that is ``ReportRunResponse.rows``, which keeps the
    row keys and the raw values exactly as they are.

    Args:
        rows: The report rows, keyed by the API's row keys.

    Returns:
        The heading row followed by one row of rendered cells per input
        row. Empty when there are no rows.
    """
    if not rows:
        return []
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    table: list[list[str]] = [[humanize_column(column) for column in columns]]
    table.extend([_format_cell(row.get(column)) for column in columns] for row in rows)
    return table


def _safe_filename(stem: str, ext: str) -> str:
    """Make a filesystem-safe report filename."""
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    safe = "".join(c if c in keep else "_" for c in stem)
    return f"{safe[:64]}_{uuid.uuid4().hex[:8]}.{ext}"


def _reports_dir() -> str:
    """Return the directory where reports are persisted.

    Honours ``BI_REPORTS_DIR`` env var; falls back to a subdir of the
    OS temp dir.
    """
    base = os.environ.get("BI_REPORTS_DIR")
    if base:
        os.makedirs(base, exist_ok=True)
        return base
    base = os.path.join(tempfile.gettempdir(), "openconstructionerp_reports")
    os.makedirs(base, exist_ok=True)
    return base


def build_csv_report(
    *,
    report_name: str,
    rows: list[dict[str, Any]],
) -> tuple[str, int]:
    """Write CSV → return ``(path, byte_size)``."""
    if not rows:
        # Empty CSV with single placeholder column for valid downloads
        path = os.path.join(
            _reports_dir(),
            _safe_filename(report_name, "csv"),
        )
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write("(no rows)\n")
        return path, os.path.getsize(path)

    path = os.path.join(
        _reports_dir(),
        _safe_filename(report_name, "csv"),
    )
    # ``csv.writer`` rather than ``DictWriter``: the rows are already
    # rendered and positional, and a dict writer keyed by heading would
    # silently drop a column whenever two row keys humanise to the same
    # heading.
    with open(path, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(_report_table(rows))
    return path, os.path.getsize(path)


def build_pdf_report(
    *,
    report_name: str,
    rows: list[dict[str, Any]],
    description: str | None = None,
) -> tuple[str, int]:
    """Render rows to a PDF table using reportlab. Returns ``(path, bytes)``.

    Falls back to a CSV → text-only PDF if reportlab is unavailable
    (every supported install ships it, but defensive).
    """
    path = os.path.join(_reports_dir(), _safe_filename(report_name, "pdf"))
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:  # pragma: no cover - reportlab is a hard dep
        logger.warning("reportlab unavailable - emitting plain-text PDF")
        with open(path, "wb") as fh:
            fh.write(b"%PDF-1.4\n% reportlab missing - see logs\n")
        return path, os.path.getsize(path)

    # Register the bundled Unicode (DejaVu) faces so Cyrillic / Greek / accented
    # Latin text renders instead of tofu boxes. Idempotent; safe to call here.
    register_pdf_fonts()

    doc = SimpleDocTemplate(
        path,
        pagesize=landscape(A4),
        leftMargin=1 * cm,
        rightMargin=1 * cm,
        topMargin=1 * cm,
        bottomMargin=1 * cm,
        title=report_name,
        **branded_doc_metadata(),
    )
    styles = getSampleStyleSheet()
    # The base styles default to Helvetica (Latin-1 only); point them at the
    # registered Unicode faces so all rendered text uses them.
    styles["Title"].fontName = BOLD_FONT
    styles["BodyText"].fontName = BODY_FONT
    story: list[Any] = []
    # The firm's letterhead, when the company profile has one, on page one only.
    # No header logo on later pages: a 1 cm top margin leaves no band to draw
    # it in, and it would land on the repeated table header. The frame pads
    # 6pt on each side, so this is the width a flowable can use.
    letterhead = branded_letterhead(doc.width - 12)
    if letterhead is not None:
        story.append(letterhead)
    story.append(Paragraph(report_name, styles["Title"]))
    if description:
        story.append(Paragraph(description, styles["BodyText"]))
    story.append(
        Paragraph(
            f"Generated {datetime.utcnow().isoformat(timespec='seconds')} UTC",
            styles["BodyText"],
        ),
    )
    story.append(Spacer(1, 0.5 * cm))

    if not rows:
        story.append(Paragraph("(no data)", styles["BodyText"]))
        doc.build(story)
        return path, os.path.getsize(path)

    # The heading is the reader's, the key stays the API's. Humanised before
    # the widths are computed, because the widths are computed from this
    # very table and a heading that wraps at word boundaries needs a
    # different amount of room than one that has to be chopped mid-word.
    table_data = _report_table(rows)
    # A dashboard export is whatever columns somebody selected, so its width is
    # not known when this code is written. Left to size itself the table grew
    # past the sheet and the right hand columns were drawn onto no paper at
    # all, which extracts perfectly and prints incomplete. Cells become
    # Paragraphs so a long value wraps, and the widths are computed because
    # reportlab spreads flowable columns across the whole frame when it is left
    # to choose, which would stretch the narrow exports that are the common
    # case. Both styles are built here rather than taken from the sample sheet
    # because a Paragraph carries its own face and colour: the FONTNAME and
    # TEXTCOLOR table commands that used to dress the header row do not reach
    # one. Nothing pre-shapes these rows; a Paragraph shapes its own text, and
    # shaping the same string twice destroys it.
    header_style = ParagraphStyle(
        "dashboard-header",
        parent=styles["BodyText"],
        fontName=BOLD_FONT,
        fontSize=8,
        leading=9.6,
        textColor=colors.whitesmoke,
        spaceBefore=0,
        spaceAfter=0,
    )
    cell_style = ParagraphStyle(
        "dashboard-cell",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=9.6,
        spaceBefore=0,
        spaceAfter=0,
    )
    # Past a point there is no width left to divide and reportlab refuses
    # the table outright, which reached the reader as a failed run and no
    # document at all. A KPI grouped by a free-text field is capped at 200
    # groups and ``run_report`` gives each its own column, so 204 columns
    # is an ordinary report rather than a stress input. The columns that
    # do not fit are dropped, and the note above the table says so - a
    # short document that admits what it left out is the only honest thing
    # to hand somebody here, and the CSV and XLSX of the same run still
    # carry every column.
    available = pdf_table_available_width(doc)
    total_columns = len(table_data[0])
    shown_columns = pdf_table_legible_columns(
        table_data,
        available,
        cell_style,
        header_style=header_style,
        header_rows=1,
    )
    if shown_columns < total_columns:
        logger.warning(
            "%s: %d of %d columns are not printed - they cannot be drawn legibly on this sheet",
            report_name,
            total_columns - shown_columns,
            total_columns,
        )
        table_data = [line[:shown_columns] for line in table_data]
        story.append(
            Paragraph(
                f"Showing {shown_columns} of {total_columns} columns. The other "
                f"{total_columns - shown_columns} are not printed here because they cannot be drawn "
                "wide enough to read on this sheet. The CSV and XLSX exports of this report carry "
                "every column.",
                styles["BodyText"],
            ),
        )
        story.append(Spacer(1, 0.3 * cm))
    col_widths = pdf_table_column_widths(
        table_data,
        available,
        cell_style,
        header_style=header_style,
        header_rows=1,
        report=report_name,
    )
    table_data = pdf_table_paragraph_rows(table_data, cell_style, header_style=header_style, header_rows=1)
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                # Backgrounds, rules and padding only. Face, size and colour
                # travel with each cell's own paragraph style now, and a table
                # command naming any of the three would be read as authoritative
                # while changing nothing on the page.
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f3f4f6")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ],
        ),
    )
    story.append(table)
    doc.build(story)
    return path, os.path.getsize(path)


def build_xlsx_report(
    *,
    report_name: str,
    rows: list[dict[str, Any]],
) -> tuple[str, int]:
    """Render rows to an XLSX using openpyxl. Returns ``(path, bytes)``.

    Returns CSV-shaped output if openpyxl is unavailable.
    """
    try:
        from openpyxl import Workbook  # type: ignore
    except ImportError:
        # Gracefully fall back to CSV with .xlsx renamed
        return build_csv_report(report_name=report_name, rows=rows)

    path = os.path.join(
        _reports_dir(),
        _safe_filename(report_name, "xlsx"),
    )
    wb = Workbook()
    ws = wb.active
    ws.title = report_name[:31]
    if rows:
        for line in _report_table(rows):
            ws.append(line)
    else:
        ws.append(["(no rows)"])
    wb.save(path)
    return path, os.path.getsize(path)


def _format_cell(v: Any, _depth: int = 0) -> str:
    """Render one value for a table cell.

    A KPI breakdown is a dict, and several carry a list. Passed to ``str``
    those print as Python source - ``{'EUR': Decimal('100000.00')}`` - which
    is not a number, not a currency, and not something a reader can parse
    even by squinting. The Decimal wrappers are the giveaway that this was
    never meant to be read: nothing consumes that shape, in any of the three
    output formats.

    So a mapping becomes ``EUR: 100,000; USD: 23,456.79`` and a sequence
    becomes ``GBP, CHF``, with each value formatted the same way a
    top-level value would be. Recursion is capped at one nested level and
    falls back to ``str`` below it, because a cell that needs two levels of
    nesting is a table design problem rather than a formatting one.

    One mapping is a record and not data: ``{"label": ..., "value": ...}``
    is what a ``top_by`` KPI puts under each of its groups, and printing
    its keys prints the query's own column names at the reader. It becomes
    ``Precast beam: 12345.6789``.

    Args:
        v: The value to render.
        _depth: Internal recursion guard.

    Returns:
        The text to print in the cell.
    """
    if v is None:
        return ""
    if v == _NULL_GROUP_KEY:
        # The same reserved key, reaching a cell rather than a heading: a
        # grouped KPI puts it in the ``label`` of every record whose group
        # had no value.
        return _NULL_GROUP_LABEL
    if isinstance(v, bool):
        # Before the Decimal branch: bool is an int, and "1.0000" for True
        # would be worse than the word.
        return str(v)
    if isinstance(v, Decimal):
        return f"{v:,.4f}".rstrip("0").rstrip(".") or "0"
    if isinstance(v, dict) and set(v) == _LABEL_VALUE_RECORD:
        # A record, not a mapping of data. The generic branch below prints
        # keys and values alike, which is right for ``{"EUR": 100000}``
        # where the key is a currency and wrong here, where the keys are
        # the names of the query's own columns: it put the words "label"
        # and "value" in front of the reader, in the document this
        # formatter exists to keep plumbing out of.
        label = _format_cell(v["label"], _depth + 1)
        value = _format_cell(v["value"], _depth + 1)
        return f"{label}: {value}" if label and value else label or value
    if _depth < 1:
        if isinstance(v, dict):
            return "; ".join(f"{k}: {_format_cell(value, _depth + 1)}" for k, value in v.items())
        if isinstance(v, (list, tuple)):
            return ", ".join(_format_cell(item, _depth + 1) for item in v)
        if isinstance(v, (set, frozenset)):
            # Sorted, so the same data does not print in two different
            # orders in two runs of the same report.
            return ", ".join(sorted(_format_cell(item, _depth + 1) for item in v))
    return str(v)


def build_report(
    *,
    output_format: str,
    report_name: str,
    rows: list[dict[str, Any]],
    description: str | None = None,
) -> tuple[str, int]:
    """Dispatch on ``output_format`` (``pdf`` / ``xlsx`` / ``csv``)."""
    fmt = (output_format or "pdf").lower()
    if fmt == "pdf":
        return build_pdf_report(
            report_name=report_name,
            rows=rows,
            description=description,
        )
    if fmt == "xlsx":
        return build_xlsx_report(report_name=report_name, rows=rows)
    if fmt == "csv":
        return build_csv_report(report_name=report_name, rows=rows)
    # Unknown - default to CSV, which is the format that survives being
    # opened by anything. It is not the machine's copy of the run: that is
    # ``ReportRunResponse.rows``, returned alongside this file with the row
    # keys and the raw values untouched.
    return build_csv_report(report_name=report_name, rows=rows)


# ── Chart export (CSV + SVG) ────────────────────────────────────────────


def export_widget_csv(
    *,
    widget_label: str,
    breakdown: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> tuple[str, int]:
    """Export a widget's value + breakdown + history as CSV.

    Used by ``GET /widgets/{id}/export?format=csv``.
    """
    path = os.path.join(
        _reports_dir(),
        _safe_filename(f"widget_{widget_label}", "csv"),
    )
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["key", "value"])
        for k, v in (breakdown or {}).items():
            writer.writerow([k, _format_cell(v)])
        if history:
            writer.writerow([])
            writer.writerow(["period_start", "period_end", "value"])
            for h in history:
                writer.writerow(
                    [
                        h.get("period_start", ""),
                        h.get("period_end", ""),
                        _format_cell(h.get("value")),
                    ],
                )
    return path, os.path.getsize(path)


def export_widget_svg(
    *,
    widget_label: str,
    history: list[dict[str, Any]],
    unit: str = "",
) -> tuple[str, int]:
    """Render a minimal line-chart of widget history as inline SVG.

    No external libs - handwritten SVG. Used by chart-export endpoint.
    """
    path = os.path.join(
        _reports_dir(),
        _safe_filename(f"widget_{widget_label}", "svg"),
    )
    points: list[tuple[float, float]] = []
    for idx, row in enumerate(history):
        try:
            v = float(row.get("value") or 0)
        except (ValueError, TypeError):
            v = 0.0
        points.append((float(idx), v))
    if not points:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="120">'
            '<text x="200" y="60" text-anchor="middle" font-family="sans-serif" '
            'font-size="14">(no history)</text></svg>'
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        return path, os.path.getsize(path)

    w, h = 400.0, 120.0
    pad = 20.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_min, x_max = min(xs), max(xs) or 1.0
    y_min, y_max = min(ys), max(ys)
    y_range = (y_max - y_min) or 1.0
    x_range = (x_max - x_min) or 1.0

    def _to_svg(x: float, y: float) -> tuple[float, float]:
        sx = pad + (x - x_min) / x_range * (w - 2 * pad)
        sy = h - pad - (y - y_min) / y_range * (h - 2 * pad)
        return sx, sy

    path_d = "M " + " L ".join(f"{sx:.1f} {sy:.1f}" for sx, sy in (_to_svg(x, y) for x, y in points))
    title = f"{widget_label} ({unit})" if unit else widget_label
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{w:.0f}" height="{h:.0f}">'
        f'<rect width="{w:.0f}" height="{h:.0f}" fill="#ffffff"/>'
        f'<path d="{path_d}" stroke="#2563eb" stroke-width="2" fill="none"/>'
        f'<text x="10" y="15" font-family="sans-serif" font-size="11" '
        f'fill="#111827">{title}</text>'
        "</svg>"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return path, os.path.getsize(path)


__all__ = [
    "build_csv_report",
    "build_pdf_report",
    "build_report",
    "build_xlsx_report",
    "export_widget_csv",
    "export_widget_svg",
    "humanize_column",
]
