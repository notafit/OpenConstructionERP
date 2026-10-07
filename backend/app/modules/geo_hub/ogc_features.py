# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""OGC API - Features (Part 1: Core) over the geometry Geo Hub already stores.

Why this exists
---------------
Every GIS client on the planet - QGIS, ArcGIS Pro, GDAL/OGR, Leaflet,
MapLibre, FME - speaks OGC API - Features. Until now the only way to look
at our coordinates from outside the product was to point a client at the
PostgreSQL database directly, which throws away the per-project access
model, the tenant isolation and the audit trail in one move. This module
serves the same rows through the same permission gate the rest of
``geo_hub`` uses, so "open it in QGIS" costs a URL and a token instead of
a database credential.

What it is NOT
--------------
There is no PostGIS here and none is wanted. Every collection is built
from plain columns (``Numeric`` latitude / longitude) and from the JSON
``FeatureCollection`` that ``GeoOverlay`` already carries, so the service
runs on the same single PostgreSQL that the rest of the platform needs
and adds no dependency.

Collections
-----------
``project-anchors``
    One point per locatable project, straight out of
    :meth:`GeoHubService.list_anchored_projects` - the same query that
    feeds the global map, so the two can never disagree about which
    projects have a location.
``geo-overlays``
    Every ``GeoOverlay`` row, exploded into its individual features.
    These are already real GeoJSON: hand-drawn boundaries, imported KML,
    flood and risk zones, and the pins the cross-module subscribers drop.
``viewpoints``
    Saved camera positions, as points at the camera's ground coordinates.

Scope and paging
----------------
Collections span every project the caller can read (owned or team
member; admins see all), archived projects excluded, exactly as the
global map does. Pass the non-standard ``project_id`` parameter to narrow
to one project - OGC API - Features permits additional parameters and
this is far kinder to a QGIS user than one collection per project.

``bbox`` is an envelope test: a feature matches when its bounding
rectangle intersects the requested one. That is the usual simple-server
reading of the standard and it is a superset of true intersection, so
nothing that should match is dropped.

To keep a single request bounded on a 3 GB server the service reads at most
:data:`MAX_SCAN_ROWS` rows per collection before filtering. When a scan
hits that ceiling the response omits ``numberMatched`` rather than
reporting a number it cannot stand behind - the standard permits the
omission, and a wrong count would make a client page into nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.geo_hub.models import GeoOverlay, GeoViewpoint
from app.modules.geo_hub.service import GeoHubService

# ── Protocol constants ───────────────────────────────────────────────────

#: The only coordinate reference system we serve. Longitude first,
#: latitude second - which is what CRS84 means and what every anchor,
#: overlay and viewpoint in the database is already stored as.
CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

#: Conformance classes we genuinely satisfy. ``html`` is deliberately
#: absent: this service returns JSON only, and claiming a class we do not
#: implement is how a client ends up asking for a page we cannot serve.
CONFORMANCE_CLASSES: tuple[str, ...] = (
    "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-common-2/1.0/conf/collections",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
)

GEOJSON_MEDIA_TYPE = "application/geo+json"
JSON_MEDIA_TYPE = "application/json"
OPENAPI_MEDIA_TYPE = "application/vnd.oai.openapi+json;version=3.0"

DEFAULT_LIMIT = 100
MAX_LIMIT = 10_000

#: Ceiling on rows read per collection request, before bbox filtering and
#: paging. Beyond this the count is unknown and reported as such.
MAX_SCAN_ROWS = 10_000

#: Separator between an overlay's row id and the index of the feature
#: inside its stored ``FeatureCollection``. A ``GeoOverlay`` row can hold
#: many features and each of them needs its own stable feature id.
FEATURE_ID_SEPARATOR = ":"


class OgcParameterError(ValueError):
    """A query parameter did not parse. The message is safe to return."""


# ── bbox ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BBox:
    """A CRS84 bounding rectangle, west / south / east / north."""

    west: float
    south: float
    east: float
    north: float

    @property
    def crosses_antimeridian(self) -> bool:
        """True when the box wraps past +/-180 degrees longitude."""
        return self.west > self.east

    def contains_point(self, lon: float, lat: float) -> bool:
        """True when the position falls inside the box (edges included)."""
        if not (self.south <= lat <= self.north):
            return False
        if self.crosses_antimeridian:
            return lon >= self.west or lon <= self.east
        return self.west <= lon <= self.east

    def intersects_bounds(self, bounds: tuple[float, float, float, float]) -> bool:
        """True when ``bounds`` (west, south, east, north) overlaps this box."""
        other_west, other_south, other_east, other_north = bounds
        if other_north < self.south or other_south > self.north:
            return False
        if self.crosses_antimeridian:
            return other_east >= self.west or other_west <= self.east
        return not (other_east < self.west or other_west > self.east)


def parse_bbox(raw: str | None) -> BBox | None:
    """Parse the OGC ``bbox`` parameter.

    Args:
        raw: Four numbers (``west,south,east,north``) or six, where the
            third and sixth are minimum and maximum elevation. Elevation
            is parsed and discarded - nothing we store is filtered by it.

    Returns:
        The rectangle, or ``None`` when the parameter was absent.

    Raises:
        OgcParameterError: The value was not four or six numbers, or the
            latitudes were out of range or inverted. ``west > east`` is
            NOT an error: that is how the standard spells a box crossing
            the antimeridian.
    """
    if raw is None or not raw.strip():
        return None
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) not in (4, 6):
        raise OgcParameterError("bbox must be 4 numbers (west,south,east,north) or 6 with elevation")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        raise OgcParameterError("bbox values must all be numbers") from None
    if len(numbers) == 6:
        west, south, east, north = numbers[0], numbers[1], numbers[3], numbers[4]
    else:
        west, south, east, north = numbers
    if not (-90.0 <= south <= 90.0 and -90.0 <= north <= 90.0):
        raise OgcParameterError("bbox latitudes must lie between -90 and 90")
    if south > north:
        raise OgcParameterError("bbox south latitude is above its north latitude")
    return BBox(west=west, south=south, east=east, north=north)


# ── datetime ─────────────────────────────────────────────────────────────


def _parse_instant(text: str) -> datetime:
    """Parse one RFC 3339 date-time. Naive input is read as UTC."""
    value = text.strip()
    if not value:
        raise OgcParameterError("datetime is empty")
    normalised = f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        raise OgcParameterError(
            f"datetime '{text}' is not RFC 3339 - expected e.g. 2026-08-21T09:00:00Z",
        ) from None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def parse_datetime(raw: str | None) -> tuple[datetime | None, datetime | None]:
    """Parse the OGC ``datetime`` parameter into an inclusive interval.

    Accepts a single instant (``2026-08-21T09:00:00Z``), a closed interval
    (``start/end``) or a half-open one where the missing half is written
    as ``..`` or left empty.

    Args:
        raw: The raw parameter value, or ``None``.

    Returns:
        ``(start, end)``, each of which may be ``None`` meaning unbounded.
        A single instant returns it as both bounds, which is the standard's
        reading: the feature's time must equal it.

    Raises:
        OgcParameterError: The value was unparseable or the interval ran
            backwards.
    """
    if raw is None or not raw.strip():
        return None, None
    text = raw.strip()
    if "/" not in text:
        instant = _parse_instant(text)
        return instant, instant
    start_text, _, end_text = text.partition("/")
    start = None if start_text.strip() in ("", "..") else _parse_instant(start_text)
    end = None if end_text.strip() in ("", "..") else _parse_instant(end_text)
    if start is not None and end is not None and start > end:
        raise OgcParameterError("datetime interval starts after it ends")
    return start, end


def parse_limit(raw: int | None) -> int:
    """Clamp the OGC ``limit`` parameter into what we are willing to serve."""
    if raw is None:
        return DEFAULT_LIMIT
    if raw < 1:
        raise OgcParameterError("limit must be 1 or more")
    return min(raw, MAX_LIMIT)


# ── GeoJSON geometry helpers ─────────────────────────────────────────────


def _walk_positions(coordinates: Any) -> Iterator[tuple[float, float]]:
    """Yield every ``(lon, lat)`` position in a GeoJSON coordinate tree."""
    if not isinstance(coordinates, (list, tuple)):
        return
    head = coordinates[:2]
    if len(head) == 2 and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in head):
        yield float(head[0]), float(head[1])
        return
    for item in coordinates:
        yield from _walk_positions(item)


def geometry_bounds(geometry: Any) -> tuple[float, float, float, float] | None:
    """Envelope of any GeoJSON geometry.

    Args:
        geometry: A GeoJSON geometry object, including ``GeometryCollection``.

    Returns:
        ``(west, south, east, north)``, or ``None`` when the geometry
        carries no position at all (a null geometry, or an empty one).
    """
    if not isinstance(geometry, dict):
        return None
    if geometry.get("type") == "GeometryCollection":
        parts = [geometry_bounds(part) for part in geometry.get("geometries") or []]
        found = [part for part in parts if part is not None]
        if not found:
            return None
        return (
            min(part[0] for part in found),
            min(part[1] for part in found),
            max(part[2] for part in found),
            max(part[3] for part in found),
        )
    positions = list(_walk_positions(geometry.get("coordinates")))
    if not positions:
        return None
    lons = [position[0] for position in positions]
    lats = [position[1] for position in positions]
    return (min(lons), min(lats), max(lons), max(lats))


def geometry_matches_bbox(geometry: Any, bbox: BBox | None) -> bool:
    """True when the geometry's envelope intersects ``bbox``.

    A geometry with no coordinates never matches a bbox filter - it has no
    position to compare - but is returned when no bbox was requested.
    """
    if bbox is None:
        return True
    bounds = geometry_bounds(geometry)
    if bounds is None:
        return False
    return bbox.intersects_bounds(bounds)


# ── Collection catalogue ─────────────────────────────────────────────────


@dataclass(frozen=True)
class CollectionSpec:
    """Static metadata for one collection this service publishes."""

    name: str
    title: str
    description: str
    temporal: bool


_ANCHORS = CollectionSpec(
    name="project-anchors",
    title="Project anchors",
    description=(
        "One point per project that has a location: either a surveyed or geocoded "
        "anchor, or usable coordinates on the project address. Spans every project "
        "you can read and excludes archived ones. Projects anchored at 0/0 are "
        "excluded - that is the placeholder written when a project is created "
        "before anyone has said where it is, not a position in the Gulf of Guinea. "
        "The feature id is the project id. Not filterable by datetime: an "
        "address-derived location has no creation time of its own."
    ),
    temporal=False,
)

_OVERLAYS = CollectionSpec(
    name="geo-overlays",
    title="Vector overlays",
    description=(
        "Vector features stored against a project: site boundaries, easements, "
        "imported GeoJSON and KML, flood and risk zones, and the markers the "
        "cross-module subscribers drop for clashes, field reports, safety "
        "incidents and non-conformities. One overlay row can hold many features, "
        "so the feature id is 'overlay-id:index'. Spans every project you can "
        "read; narrow it with the project_id parameter. Filterable by datetime "
        "on the overlay's creation time."
    ),
    temporal=True,
)

_VIEWPOINTS = CollectionSpec(
    name="viewpoints",
    title="Saved viewpoints",
    description=(
        "Saved camera positions for the 3D project map, served as points at the "
        "camera's ground coordinates with heading, pitch, roll and camera "
        "altitude as attributes. Spans every project you can read; narrow it "
        "with the project_id parameter. Filterable by datetime on creation time."
    ),
    temporal=True,
)

COLLECTIONS: tuple[CollectionSpec, ...] = (_ANCHORS, _OVERLAYS, _VIEWPOINTS)

_COLLECTIONS_BY_NAME: dict[str, CollectionSpec] = {spec.name: spec for spec in COLLECTIONS}


def get_collection(name: str) -> CollectionSpec | None:
    """Look up a collection spec by its id, or ``None`` when unknown."""
    return _COLLECTIONS_BY_NAME.get(name)


# ── Feature construction ─────────────────────────────────────────────────


def _as_float(value: Any) -> float | None:
    """Coerce a Decimal / int / float / numeric string to float, or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _iso(value: datetime | None) -> str | None:
    """Render a timestamp as RFC 3339 UTC, or ``None``."""
    if value is None:
        return None
    stamped = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return stamped.astimezone(UTC).isoformat().replace("+00:00", "Z")


def anchor_feature(row: dict[str, Any]) -> dict[str, Any] | None:
    """Build the anchor feature for one row of ``list_anchored_projects``.

    Returns ``None`` when the row has no usable position, which currently
    means the 0/0 placeholder anchor written by the ``projects.created``
    subscriber. ``map_config`` already treats 0/0 as "not located"; this
    keeps a client from painting a null-island pin for every project that
    has not been placed yet.
    """
    lon = _as_float(row.get("lon"))
    lat = _as_float(row.get("lat"))
    if lon is None or lat is None:
        return None
    if lon == 0.0 and lat == 0.0:
        return None
    anchor_id = row.get("anchor_id")
    return {
        "type": "Feature",
        "id": str(row["project_id"]),
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "project_id": str(row["project_id"]),
            "project_name": row.get("project_name"),
            "anchor_id": str(anchor_id) if anchor_id else None,
            "anchored": anchor_id is not None,
            "altitude_m": _as_float(row.get("alt")) or 0.0,
            "region_code": row.get("region_code"),
            "address": row.get("address"),
            "project_address": row.get("project_address_text"),
            "project_type": row.get("project_type"),
            "status": row.get("status"),
        },
    }


def overlay_features(overlay: GeoOverlay) -> list[dict[str, Any]]:
    """Explode one ``GeoOverlay`` row into individual GeoJSON features.

    The stored ``geojson`` column normally holds a ``FeatureCollection``,
    but the import paths also accept a bare ``Feature`` or a bare geometry,
    so all three shapes are handled. Each feature keeps whatever properties
    it was stored with; the overlay's own identity is stamped on top, so a
    client can always tell which row and which project a feature came from
    even if the imported file happened to use the same property names.
    """
    stored = overlay.geojson if isinstance(overlay.geojson, dict) else {}
    kind = stored.get("type")
    if kind == "FeatureCollection":
        raw_features = [item for item in (stored.get("features") or []) if isinstance(item, dict)]
    elif kind == "Feature":
        raw_features = [stored]
    elif kind:
        raw_features = [{"type": "Feature", "geometry": stored, "properties": {}}]
    else:
        raw_features = []

    stamp = {
        "overlay_id": str(overlay.id),
        "overlay_name": overlay.name,
        "overlay_kind": overlay.kind,
        "project_id": str(overlay.project_id),
        "is_visible": bool(overlay.is_visible),
        "source_file": overlay.source_file,
        "source_event_id": overlay.source_event_id,
        "created_at": _iso(overlay.created_at),
        "updated_at": _iso(overlay.updated_at),
    }

    built: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_features):
        properties = dict(raw.get("properties") or {}) if isinstance(raw.get("properties"), dict) else {}
        properties.update(stamp)
        built.append(
            {
                "type": "Feature",
                "id": f"{overlay.id}{FEATURE_ID_SEPARATOR}{index}",
                "geometry": raw.get("geometry"),
                "properties": properties,
            },
        )
    return built


def viewpoint_feature(viewpoint: GeoViewpoint) -> dict[str, Any] | None:
    """Build the point feature for one saved camera viewpoint."""
    lon = _as_float(viewpoint.camera_lon)
    lat = _as_float(viewpoint.camera_lat)
    if lon is None or lat is None:
        return None
    return {
        "type": "Feature",
        "id": str(viewpoint.id),
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "viewpoint_id": str(viewpoint.id),
            "project_id": str(viewpoint.project_id),
            "name": viewpoint.name,
            "description": viewpoint.description,
            "camera_altitude_m": _as_float(viewpoint.camera_alt) or 0.0,
            "heading_deg": _as_float(viewpoint.heading) or 0.0,
            "pitch_deg": _as_float(viewpoint.pitch) or 0.0,
            "roll_deg": _as_float(viewpoint.roll) or 0.0,
            "created_at": _iso(viewpoint.created_at),
            "updated_at": _iso(viewpoint.updated_at),
        },
    }


# ── Links and envelopes ──────────────────────────────────────────────────


def link(href: str, rel: str, media_type: str, title: str) -> dict[str, str]:
    """Build one OGC link object."""
    return {"href": href, "rel": rel, "type": media_type, "title": title}


def _with_query(url: str, query: dict[str, Any]) -> str:
    """Append a query string, dropping keys whose value is ``None``."""
    pairs = [(key, str(value)) for key, value in query.items() if value is not None]
    if not pairs:
        return url
    return f"{url}?{urlencode(pairs)}"


def items_links(
    *,
    items_url: str,
    collection_url: str,
    query: dict[str, Any],
    offset: int,
    limit: int,
    number_returned: int,
    number_matched: int | None,
) -> list[dict[str, str]]:
    """Build ``self`` / ``next`` / ``prev`` / ``collection`` links for a page.

    ``next`` is emitted when there is provably more to fetch: either the
    count is known and this page did not reach it, or the count is unknown
    (the scan hit its ceiling) and the page came back full, which is the
    only honest signal left that another page may exist.
    """
    base = dict(query)
    links = [
        link(
            _with_query(items_url, {**base, "offset": offset or None, "limit": limit}),
            "self",
            GEOJSON_MEDIA_TYPE,
            "This page of features",
        ),
    ]
    if number_matched is None:
        has_next = number_returned >= limit
    else:
        has_next = offset + number_returned < number_matched
    if has_next:
        links.append(
            link(
                _with_query(items_url, {**base, "offset": offset + limit, "limit": limit}),
                "next",
                GEOJSON_MEDIA_TYPE,
                "Next page",
            ),
        )
    if offset > 0:
        previous = max(offset - limit, 0)
        links.append(
            link(
                _with_query(items_url, {**base, "offset": previous or None, "limit": limit}),
                "prev",
                GEOJSON_MEDIA_TYPE,
                "Previous page",
            ),
        )
    links.append(link(collection_url, "collection", JSON_MEDIA_TYPE, "The collection these features belong to"))
    return links


def feature_collection(
    features: list[dict[str, Any]],
    *,
    number_matched: int | None,
    links: list[dict[str, str]],
) -> dict[str, Any]:
    """Wrap features in an OGC-shaped GeoJSON ``FeatureCollection``.

    ``numberMatched`` is omitted entirely when the count is unknown. The
    standard allows that; reporting a guess would make a client either
    stop early or page forever.
    """
    body: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": features,
        "numberReturned": len(features),
        "timeStamp": _iso(datetime.now(UTC)),
        "links": links,
    }
    if number_matched is not None:
        body["numberMatched"] = number_matched
    return body


def parse_feature_id(raw: str) -> tuple[uuid.UUID, int] | None:
    """Split an overlay feature id into its row id and feature index.

    Returns ``None`` when the id is not the ``uuid:index`` shape, which is
    how an unknown feature turns into a 404 rather than a 500.
    """
    row_text, separator, index_text = raw.partition(FEATURE_ID_SEPARATOR)
    if not separator:
        row_text, index_text = raw, "0"
    try:
        row_id = uuid.UUID(row_text)
        index = int(index_text)
    except (TypeError, ValueError):
        return None
    if index < 0:
        return None
    return row_id, index


# ── Service ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FeaturePage:
    """One page of features plus what the envelope needs to describe it."""

    features: list[dict[str, Any]]
    number_matched: int | None


class OgcFeaturesService:
    """Read-only OGC API - Features view over Geo Hub's stored geometry.

    Every read goes through the same access rules as the rest of the
    module: :meth:`GeoHubService._verify_project_owner` for an explicitly
    named project, and the owner-or-team-member scoping that the global
    map already uses for everything else. Nothing here can see a project
    that the map would not show the same caller.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.geo = GeoHubService(session)

    # ── Access scoping ──────────────────────────────────────────────

    def _accessible_project_ids(self, payload: dict[str, Any] | None) -> Any:
        """A subquery selecting the project ids this caller may read.

        Mirrors :meth:`GeoHubService.list_anchored_projects`: admins get
        every non-archived project, everyone else gets the ones they own
        plus the ones they are a team member of. Archived projects are
        excluded from all of them so a collection and the global map agree
        on which projects still exist.
        """
        from sqlalchemy import or_

        from app.modules.projects.models import Project
        from app.modules.teams.access import member_project_ids_subquery

        stmt = select(Project.id).where(Project.status != "archived")
        is_admin = payload is not None and payload.get("role") == "admin"
        user_id = payload.get("sub") or payload.get("user_id") if payload else None
        if not is_admin:
            if user_id is None:
                # No identity: select nothing rather than everything. The
                # route is already gated, so this is defence in depth.
                stmt = stmt.where(Project.id.is_(None))
            else:
                stmt = stmt.where(
                    or_(
                        Project.owner_id == user_id,
                        Project.id.in_(member_project_ids_subquery(user_id)),
                    ),
                )
        return stmt.scalar_subquery()

    async def _resolve_project_scope(
        self,
        project_id: uuid.UUID | None,
        payload: dict[str, Any] | None,
    ) -> uuid.UUID | None:
        """Validate an explicit ``project_id`` filter, or return ``None``.

        A project the caller cannot reach collapses to 404, matching the
        rest of geo_hub, so the parameter cannot be turned into a probe for
        which project ids exist.
        """
        if project_id is None:
            return None
        await self.geo._verify_project_owner(
            project_id,
            payload,
            not_found_detail="Project not found",
        )
        return project_id

    # ── Feature loading ─────────────────────────────────────────────

    async def _load_anchor_features(
        self,
        payload: dict[str, Any] | None,
        *,
        project_id: uuid.UUID | None,
    ) -> tuple[list[dict[str, Any]], bool]:
        rows = await self.geo.list_anchored_projects(payload, limit=MAX_SCAN_ROWS)
        truncated = len(rows) >= MAX_SCAN_ROWS
        features: list[dict[str, Any]] = []
        for row in rows:
            if project_id is not None and str(row.get("project_id")) != str(project_id):
                continue
            feature = anchor_feature(row)
            if feature is not None:
                features.append(feature)
        return features, truncated

    async def _load_overlay_features(
        self,
        payload: dict[str, Any] | None,
        *,
        project_id: uuid.UUID | None,
        start: datetime | None,
        end: datetime | None,
    ) -> tuple[list[dict[str, Any]], bool]:
        stmt = select(GeoOverlay).where(GeoOverlay.project_id.in_(self._accessible_project_ids(payload)))
        if project_id is not None:
            stmt = stmt.where(GeoOverlay.project_id == project_id)
        if start is not None:
            stmt = stmt.where(GeoOverlay.created_at >= start)
        if end is not None:
            stmt = stmt.where(GeoOverlay.created_at <= end)
        stmt = stmt.order_by(GeoOverlay.created_at.asc(), GeoOverlay.id.asc()).limit(MAX_SCAN_ROWS)
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        features: list[dict[str, Any]] = []
        for row in rows:
            features.extend(overlay_features(row))
        return features, len(rows) >= MAX_SCAN_ROWS

    async def _load_viewpoint_features(
        self,
        payload: dict[str, Any] | None,
        *,
        project_id: uuid.UUID | None,
        start: datetime | None,
        end: datetime | None,
    ) -> tuple[list[dict[str, Any]], bool]:
        stmt = select(GeoViewpoint).where(GeoViewpoint.project_id.in_(self._accessible_project_ids(payload)))
        if project_id is not None:
            stmt = stmt.where(GeoViewpoint.project_id == project_id)
        if start is not None:
            stmt = stmt.where(GeoViewpoint.created_at >= start)
        if end is not None:
            stmt = stmt.where(GeoViewpoint.created_at <= end)
        stmt = stmt.order_by(GeoViewpoint.created_at.asc(), GeoViewpoint.id.asc()).limit(MAX_SCAN_ROWS)
        result = await self.session.execute(stmt)
        features = [viewpoint_feature(row) for row in result.scalars().all()]
        built = [feature for feature in features if feature is not None]
        return built, len(features) >= MAX_SCAN_ROWS

    async def load_all(
        self,
        spec: CollectionSpec,
        payload: dict[str, Any] | None,
        *,
        project_id: uuid.UUID | None,
        start: datetime | None,
        end: datetime | None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Load every feature in a collection that passes the non-spatial filters.

        Returns the features and whether the underlying scan hit its row
        ceiling, which is what decides if ``numberMatched`` can be trusted.
        """
        if spec is _ANCHORS:
            return await self._load_anchor_features(payload, project_id=project_id)
        if spec is _OVERLAYS:
            return await self._load_overlay_features(payload, project_id=project_id, start=start, end=end)
        return await self._load_viewpoint_features(payload, project_id=project_id, start=start, end=end)

    async def page(
        self,
        spec: CollectionSpec,
        payload: dict[str, Any] | None,
        *,
        project_id: uuid.UUID | None,
        bbox: BBox | None,
        start: datetime | None,
        end: datetime | None,
        offset: int,
        limit: int,
    ) -> FeaturePage:
        """Filter, count and slice one page of a collection.

        The order matters and is the whole reason paging is done here
        rather than in SQL: an overlay row explodes into an unknown number
        of features, so a SQL ``OFFSET`` would skip rows, not features, and
        page two would silently start in the wrong place.
        """
        features, truncated = await self.load_all(
            spec,
            payload,
            project_id=project_id,
            start=start,
            end=end,
        )
        if bbox is not None:
            features = [feature for feature in features if geometry_matches_bbox(feature.get("geometry"), bbox)]
        number_matched = None if truncated else len(features)
        return FeaturePage(features=features[offset : offset + limit], number_matched=number_matched)

    async def one(
        self,
        spec: CollectionSpec,
        feature_id: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Fetch a single feature by id, or ``None`` when it is not there.

        A feature in a project the caller cannot read is "not there" - the
        same 404-not-403 rule the rest of the module follows, so this
        endpoint cannot be used to test whether an id exists.
        """
        if spec is _ANCHORS:
            return await self._one_anchor(feature_id, payload)
        if spec is _OVERLAYS:
            return await self._one_overlay(feature_id, payload)
        return await self._one_viewpoint(feature_id, payload)

    async def _one_anchor(self, feature_id: str, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        try:
            project_id = uuid.UUID(feature_id)
        except (TypeError, ValueError):
            return None
        # Deliberately answered from the same query that builds the
        # collection: a single feature that disagreed with the list it came
        # from would be a worse bug than the cost of this scan.
        features, _ = await self._load_anchor_features(payload, project_id=project_id)
        return features[0] if features else None

    async def _one_overlay(self, feature_id: str, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        parsed = parse_feature_id(feature_id)
        if parsed is None:
            return None
        overlay_id, index = parsed
        overlay = await self.session.get(GeoOverlay, overlay_id)
        if overlay is None:
            return None
        await self.geo._verify_project_owner(
            overlay.project_id,
            payload,
            not_found_detail="Feature not found",
        )
        features = overlay_features(overlay)
        if index >= len(features):
            return None
        return features[index]

    async def _one_viewpoint(self, feature_id: str, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        try:
            viewpoint_id = uuid.UUID(feature_id)
        except (TypeError, ValueError):
            return None
        viewpoint = await self.session.get(GeoViewpoint, viewpoint_id)
        if viewpoint is None:
            return None
        await self.geo._verify_project_owner(
            viewpoint.project_id,
            payload,
            not_found_detail="Feature not found",
        )
        return viewpoint_feature(viewpoint)


__all__ = [
    "COLLECTIONS",
    "CONFORMANCE_CLASSES",
    "CRS84",
    "DEFAULT_LIMIT",
    "GEOJSON_MEDIA_TYPE",
    "JSON_MEDIA_TYPE",
    "MAX_LIMIT",
    "MAX_SCAN_ROWS",
    "OPENAPI_MEDIA_TYPE",
    "BBox",
    "CollectionSpec",
    "FeaturePage",
    "OgcFeaturesService",
    "OgcParameterError",
    "anchor_feature",
    "feature_collection",
    "geometry_bounds",
    "geometry_matches_bbox",
    "get_collection",
    "items_links",
    "link",
    "overlay_features",
    "parse_bbox",
    "parse_datetime",
    "parse_feature_id",
    "parse_limit",
    "viewpoint_feature",
]
