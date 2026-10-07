# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Lightweight point-cloud header sniff.

This is the cheap "preview" half of the reality-capture pipeline (plan section
3 step 1 and section 9): the moment a scan finishes uploading we read only the
file *header* - point count, bounding box, scale/offset, units, which scalar
fields the cloud carries - so the scan list shows real extents instantly,
WITHOUT decoding the 5-200 GB point payload.

It is the one library exception the plan grants the 3 GB core (section 9: "the
backend imports zero point-cloud libraries, exception: ``laspy`` for header
sniff"):

* LAS / LAZ / COPC  -> ``laspy.open`` reads the header + VLRs only (hundreds of
  bytes to a few KB), never the point records.
* E57              -> ``pye57`` exposes per-scan point counts and Cartesian
  bounds from the XML section without streaming the binary points.

Both readers are optional. When neither is installed the sniff raises
:class:`HeaderSniffUnavailable` so the caller can record "metadata pending" and
the platform still installs and runs without the point-cloud extra. A present
but corrupt / truncated header raises :class:`HeaderSniffError`.

Like :mod:`decode`, this module is intentionally pure and synchronous: it takes
either a local file path or a header byte prefix, returns a plain dataclass, and
never touches the database, the session or storage. The service layer wraps it
in ``asyncio.to_thread`` and owns all I/O - and for object storage it only ever
hands this module a bounded header prefix, never the whole blob.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# How many leading bytes of the raw container are enough to carry the full
# header and every VLR / EVLR for any real-world LAS/LAZ file. The public LAS
# header is 227-375 bytes; VLRs that hold CRS GeoKeys / WKT add a few KB. 4 MiB
# is generous and still trivially small next to a multi-hundred-GB cloud, so the
# object-storage path range-reads only this prefix.
HEADER_PREFIX_BYTES: int = 4 * 1024 * 1024

_LAS_FORMATS = {"las", "laz", "copc"}
_E57_FORMATS = {"e57"}


class HeaderSniffUnavailable(RuntimeError):
    """Raised when no installed reader can sniff the requested format.

    Carries the offending format and the reader that would handle it so the
    caller can record an honest "metadata pending - reader not installed" state
    instead of failing the upload.
    """

    def __init__(self, fmt: str, reader: str) -> None:
        self.fmt = fmt
        self.reader = reader
        super().__init__(f"No header reader available for {fmt!r} (needs {reader})")


class HeaderSniffError(RuntimeError):
    """Raised when a header is present but cannot be parsed (truncated upload,
    wrong extension, empty container)."""


@dataclass(slots=True)
class ScanHeader:
    """The cheap, header-only summary of a reality-capture scan.

    Everything here comes from the container header / VLRs, never from decoding
    the points. ``point_count`` is the writer-declared count; ``bbox_min`` /
    ``bbox_max`` are the writer-declared extents in the cloud's own units. The
    scalar-field flags say which channels the points carry so the UI can promise
    "true colour" or "intensity ramp" before a single point is streamed.
    """

    point_count: int
    bbox_min: tuple[float, float, float] | None
    bbox_max: tuple[float, float, float] | None
    units: str  # "m" by default; LAS rarely declares non-metric linear units
    has_rgb: bool
    has_intensity: bool
    has_classification: bool
    # Free-form, render-irrelevant facts surfaced as "what's in this scan":
    # point_format id, extra/scalar dimension names, scale/offset, reader, etc.
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def coordinate_ranges(self) -> dict[str, list[float]] | None:
        """Per-axis ``[min, max]`` coordinate ranges, or ``None`` when unknown."""
        if self.bbox_min is None or self.bbox_max is None:
            return None
        return {
            "x": [self.bbox_min[0], self.bbox_max[0]],
            "y": [self.bbox_min[1], self.bbox_max[1]],
            "z": [self.bbox_min[2], self.bbox_max[2]],
        }


def _finite_triplet(values: Any) -> tuple[float, float, float] | None:
    """Coerce a 3-sequence into a finite float triplet, or ``None``.

    A header whose mins/maxs are absent, the wrong length, or non-finite (a
    writer that left them at NaN/inf) yields ``None`` so we never persist a
    poisoned bbox.
    """
    try:
        seq = [float(v) for v in values]
    except (TypeError, ValueError):
        return None
    if len(seq) < 3:
        return None
    triplet = seq[:3]
    if not all(math.isfinite(v) for v in triplet):
        return None
    return (triplet[0], triplet[1], triplet[2])


# ── LAS / LAZ / COPC ─────────────────────────────────────────────────────


def _las_units(header: Any) -> str:
    """Best-effort linear unit for a LAS header.

    LAS encodes units in the GeoKey ``ProjLinearUnitsGeoKey`` inside a VLR; the
    overwhelming majority of construction scans are metric and laspy does not
    surface the unit directly, so we default to metres and only flag feet when a
    WKT/GeoKey VLR clearly says so. The value is advisory metadata, not a
    transform input.
    """
    try:
        for vlr in list(getattr(header, "vlrs", []) or []):
            text = ""
            wkt = getattr(vlr, "string", None) or getattr(vlr, "wkt", None)
            if isinstance(wkt, (bytes, bytearray)):
                text = wkt.decode("ascii", "replace")
            elif isinstance(wkt, str):
                text = wkt
            low = text.lower()
            if "usfeet" in low or "us survey foot" in low or "foot_us" in low:
                return "ft"
            if 'unit["foot"' in low or "international foot" in low:
                return "ft"
    except Exception:  # noqa: BLE001 - units are advisory; never fail the sniff
        return "m"
    return "m"


def _sniff_las(reader: Any) -> ScanHeader:
    """Build a :class:`ScanHeader` from an open laspy reader (header only)."""
    header = getattr(reader, "header", None)
    if header is None:
        raise HeaderSniffError("LAS/LAZ reader exposed no header")

    # Point count: prefer the explicit count, fall back to the legacy field.
    raw_count = getattr(header, "point_count", None)
    if raw_count is None:
        raw_count = getattr(header, "point_records_count", 0)
    try:
        point_count = max(0, int(raw_count))
    except (TypeError, ValueError):
        point_count = 0

    bbox_min = _finite_triplet(getattr(header, "mins", None))
    bbox_max = _finite_triplet(getattr(header, "maxs", None))

    point_format = getattr(header, "point_format", None)
    dims: set[str] = set()
    extra_dims: list[str] = []
    fmt_id: int | None = None
    if point_format is not None:
        try:
            dims = {str(d) for d in point_format.dimension_names}
        except Exception:  # noqa: BLE001 - older laspy may differ
            dims = set()
        try:
            extra_dims = [str(d) for d in getattr(point_format, "extra_dimension_names", [])]
        except Exception:  # noqa: BLE001
            extra_dims = []
        fmt_id = getattr(point_format, "id", None)

    has_rgb = {"red", "green", "blue"} <= dims
    has_intensity = "intensity" in dims
    has_classification = "classification" in dims

    extra: dict[str, Any] = {
        "reader": "laspy",
        "point_format_id": fmt_id,
        "extra_dimensions": extra_dims,
    }
    version = getattr(header, "version", None)
    if version is not None:
        extra["las_version"] = str(version)
    scales = _finite_triplet(getattr(header, "scales", None))
    offsets = _finite_triplet(getattr(header, "offsets", None))
    if scales is not None:
        extra["scales"] = list(scales)
    if offsets is not None:
        extra["offsets"] = list(offsets)
    # has_gps_time / has_waveform are nice "what's in this scan" facts.
    extra["has_gps_time"] = "gps_time" in dims

    return ScanHeader(
        point_count=point_count,
        bbox_min=bbox_min,
        bbox_max=bbox_max,
        units=_las_units(header),
        has_rgb=has_rgb,
        has_intensity=has_intensity,
        has_classification=has_classification,
        extra=extra,
    )


def _open_las(path: Path | None, prefix: bytes | None) -> ScanHeader:
    try:
        import laspy  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised via the pending path
        raise HeaderSniffUnavailable("las", "laspy") from exc

    # ``laspy.open`` reads only the header + VLRs and leaves the point records
    # untouched, so this stays a header sniff even for a 200 GB file on the
    # local backend. For object storage we feed it a bounded header prefix.
    try:
        if path is not None:
            with laspy.open(str(path)) as reader:
                return _sniff_las(reader)
        with laspy.open(io.BytesIO(prefix or b"")) as reader:
            return _sniff_las(reader)
    except HeaderSniffError:
        raise
    except Exception as exc:  # noqa: BLE001 - laspy raises many error types
        raise HeaderSniffError(f"Could not read LAS/LAZ header: {exc}") from exc


# ── E57 ────────────────────────────────────────────────────────────────────


def _sniff_e57(path: Path) -> ScanHeader:
    try:
        import pye57  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised via the pending path
        raise HeaderSniffUnavailable("e57", "pye57") from exc

    try:
        handle = pye57.E57(str(path))
    except Exception as exc:  # noqa: BLE001 - pye57 raises bare RuntimeError
        raise HeaderSniffError(f"Could not open E57: {exc}") from exc

    scan_count = max(0, int(getattr(handle, "scan_count", 0)))
    if scan_count == 0:
        raise HeaderSniffError("E57 declares no scans")

    total = 0
    mins = [math.inf, math.inf, math.inf]
    maxs = [-math.inf, -math.inf, -math.inf]
    has_rgb = False
    has_intensity = False
    for idx in range(scan_count):
        try:
            hdr = handle.get_header(idx)
        except Exception as exc:  # noqa: BLE001
            raise HeaderSniffError(f"Could not read E57 scan {idx} header: {exc}") from exc
        try:
            total += int(getattr(hdr, "point_count", 0))
        except (TypeError, ValueError):
            pass
        # pye57 surfaces per-axis bounds and the field name list on the header
        # without reading the binary point blob.
        for axis, lo_attr, hi_attr in (
            (0, "xMinimum", "xMaximum"),
            (1, "yMinimum", "yMaximum"),
            (2, "zMinimum", "zMaximum"),
        ):
            lo = getattr(hdr, lo_attr, None)
            hi = getattr(hdr, hi_attr, None)
            if lo is not None and math.isfinite(float(lo)):
                mins[axis] = min(mins[axis], float(lo))
            if hi is not None and math.isfinite(float(hi)):
                maxs[axis] = max(maxs[axis], float(hi))
        try:
            fields = {str(f).lower() for f in getattr(hdr, "point_fields", []) or []}
        except Exception:  # noqa: BLE001
            fields = set()
        if {"colorred", "colorgreen", "colorblue"} & fields:
            has_rgb = True
        if "intensity" in fields:
            has_intensity = True

    bbox_min = tuple(mins) if all(math.isfinite(v) for v in mins) else None
    bbox_max = tuple(maxs) if all(math.isfinite(v) for v in maxs) else None

    return ScanHeader(
        point_count=max(0, total),
        bbox_min=bbox_min,  # type: ignore[arg-type]
        bbox_max=bbox_max,  # type: ignore[arg-type]
        units="m",  # E57 Cartesian coordinates are metres by spec
        has_rgb=has_rgb,
        has_intensity=has_intensity,
        has_classification=False,  # classification lives downstream, not in raw E57
        extra={"reader": "pye57", "scan_count": scan_count},
    )


# ── Public entry points ──────────────────────────────────────────────────


def sniff_header_from_path(path: Path, fmt: str) -> ScanHeader:
    """Sniff a raw container's header from a local file path.

    Reads only the header (LAS via ``laspy.open``, E57 via ``pye57`` XML), never
    the point payload. ``fmt`` is the normalised upload format. Raises
    :class:`HeaderSniffUnavailable` when the reader is not installed and
    :class:`HeaderSniffError` when the header is present but undecodable.
    """
    fmt = (fmt or "").lower().strip()
    if fmt in _LAS_FORMATS:
        return _open_las(path, None)
    if fmt in _E57_FORMATS:
        return _sniff_e57(path)
    raise HeaderSniffUnavailable(fmt or "unknown", "a supported header reader (laspy or pye57)")


def sniff_header_from_prefix(prefix: bytes, fmt: str) -> ScanHeader:
    """Sniff a header from a byte prefix read off object storage.

    The service range-reads only :data:`HEADER_PREFIX_BYTES` from MinIO/S3 and
    hands them here, so a 200 GB cloud is never pulled into the 3 GB core. Only
    the seekable LAS/LAZ family can be sniffed from a prefix; E57 needs a real
    file handle, so a prefix sniff of E57 reports the reader as the limiter (the
    service then spills E57 headers to a temp file instead).
    """
    fmt = (fmt or "").lower().strip()
    if fmt in _LAS_FORMATS:
        return _open_las(None, prefix)
    if fmt in _E57_FORMATS:
        # E57's libE57 reader needs random access to a file; a head prefix is
        # not enough. Signal "use the file path" rather than guess.
        raise HeaderSniffUnavailable("e57", "pye57 (needs a file path, not a byte prefix)")
    raise HeaderSniffUnavailable(fmt or "unknown", "a supported header reader (laspy or pye57)")


__all__ = [
    "HEADER_PREFIX_BYTES",
    "HeaderSniffError",
    "HeaderSniffUnavailable",
    "ScanHeader",
    "sniff_header_from_path",
    "sniff_header_from_prefix",
]
