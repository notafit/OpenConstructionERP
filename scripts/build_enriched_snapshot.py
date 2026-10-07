"""‌⁠‍Build the ``cwicr_en_v3_enriched`` Qdrant collection from ``cwicr_en_v3``.

Background
----------
The v3 ``cwicr_en_v3`` snapshot from DDC encodes ``rate_code`` text only
(opaque tokens like ``RILI_KANE_KAKAME_KAME``). The BGE cross-encoder
re-rank stage operates on ``(query, passage)`` pairs where the passage
collapses to that same opaque code — there's no descriptive text in the
payload for the reranker to discriminate against. The result is a logit
collapse to the 0.001-0.04 sigmoid band: every candidate within a trade
family looks identical to BGE.

The CWICR payload *does* carry rich descriptive metadata fields
(``collection_name``, ``material_class``, ``ifc_class``,
``masterformat_division``, ``category_type``, ``installation_method``,
``construction_stage``, ``ost_category``, ``uniformat_group``,
``rate_unit``). Concatenated they read as a human-readable line — good
enough for a cross-encoder to score semantically.

What this script does
---------------------

1. Scrolls every point in ``cwicr_en_v3``, reads its payload.
2. Synthesises a ``passage_text`` field from the descriptive payload
   fields (see :func:`_build_passage_text`).
3. Re-encodes ``passage_text`` with BGE-M3 (same model the v3 snapshot
   was built with — ``BAAI/bge-m3``, FP32, 1024-dim dense + sparse).
4. Writes the point to a new collection ``cwicr_en_v3_enriched`` with:
   - Same vector schema as the source (named ``dense`` 1024d cosine
     + sparse ``sparse``).
   - All original payload fields preserved.
   - Two new fields added: ``description`` and ``passage_text``.

Idempotent: re-running picks up where the last run left off because we
check the destination collection's existing IDs before encoding. Run-
to-run interruptible — kill and restart, no data loss.

Usage
-----

Local one-shot, full collection (~30 min CPU):

    python scripts/build_enriched_snapshot.py

Sample (first 5000 points, useful for an A/B sanity test):

    python scripts/build_enriched_snapshot.py --limit 5000

Override source/target collections (for E.g. ``cwicr_de_v3`` later):

    python scripts/build_enriched_snapshot.py \
        --source cwicr_de_v3 \
        --target cwicr_de_v3_enriched

Dry-run (synthesise + log first 3 passages, do not encode/write):

    python scripts/build_enriched_snapshot.py --dry-run

Constraints honoured (per the spec doc):
- Does NOT delete ``cwicr_en_v3``.
- Does NOT change embedding dimensions or model.
- Does NOT remove existing payload fields — only ADDS two new ones.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except ImportError as exc:
    print(f"ERROR: qdrant_client not installed: {exc}", file=sys.stderr)
    sys.exit(2)


# ── Payload → passage synthesis ──────────────────────────────────────────


def _normalise_text(s: Any) -> str:
    """‌⁠‍Convert a payload field to a clean string (TitleCase ALL-CAPS)."""
    if s is None:
        return ""
    t = str(s).strip()
    if not t:
        return ""
    # Title-case ALL-CAPS fields like "REPAIR AND CONSTRUCTION WORKS" so
    # the encoder sees natural sentence-case casing, not all-caps shouting.
    if t.isupper() and len(t) > 3:
        t = t.title()
    return t


def _split_camelcase(s: str) -> str:
    """‌⁠‍Split CamelCase / PascalCase into space-separated words.

    ``ReinforcedConcrete`` → ``Reinforced Concrete``
    ``IfcSlab`` → ``Ifc Slab``
    ``IfcCovering`` → ``Ifc Covering``
    ``CLADDING`` → ``Cladding`` (pure ALL-CAPS title-cased; no per-letter split)
    ``USERDEFINED`` → ``Userdefined``

    BGE-M3's subword tokeniser handles "ReinforcedConcrete" as a single
    OOV chunk, defeating the lexical channel's sparse signal. Splitting
    on capital boundaries gives the sparse channel real tokens to hit.

    Pure ALL-CAPS short tokens (length <= 16 and 100% uppercase) are
    title-cased rather than split letter-by-letter — early synthesis
    runs produced ``C L A D D I N G`` for the ``CLADDING`` IFC
    predefined-type which is worse than the unsplit form for the
    encoder.
    """
    if not s:
        return ""
    # Pure ALL-CAPS → title-case, do not split letter-by-letter.
    if s.isupper() and len(s) <= 16:
        return s.title()

    out: list[str] = []
    cur = ""
    for ch in s:
        if ch.isupper() and cur:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return " ".join(out)


def _mf_label(mf: str) -> str:
    """Render a US division/section code as a passage-ready label.

    Maps the leading 2-digit prefix (``03``) to our scope description
    (``Cast-in-place and precast concrete work``) so the cross-encoder
    sees the discipline keywords, not just digits. Falls back to a
    digits-only render when the prefix is unknown — better than dropping
    the signal entirely.
    """
    if not mf:
        return ""
    mf_clean = mf.strip()
    head = mf_clean.split()[0] if " " in mf_clean else mf_clean[:2]
    label = _MF_DIVISION_LABELS.get(head)
    if label:
        return f"Division {mf_clean} {label}"
    return f"Division {mf_clean}"


# Division scope descriptions. Numbers are interoperability facts; the
# wording is our own and matches us_pack/config.py - the proprietary
# division titles must never be bundled (licensing denylist).
_MF_DIVISION_LABELS: dict[str, str] = {
    "01": "General project requirements and temporary provisions",
    "02": "Demolition, site assessment and existing structures",
    "03": "Cast-in-place and precast concrete work",
    "04": "Brick, block and stone work",
    "05": "Structural and miscellaneous metal work",
    "06": "Carpentry, millwork and composite framing",
    "07": "Roofing, waterproofing and insulation",
    "08": "Doors, windows and glazed assemblies",
    "09": "Interior finishing: drywall, flooring, painting",
    "10": "Built-in specialty items and signage",
    "11": "Fixed building equipment",
    "12": "Furniture, casework and window treatments",
    "13": "Pre-engineered and special-purpose structures",
    "14": "Elevators, escalators and lifts",
    "21": "Sprinkler and fire-suppression systems",
    "22": "Piping systems and sanitary fixtures",
    "23": "Heating, cooling and ventilation systems",
    "25": "Building automation and controls integration",
    "26": "Power distribution and lighting systems",
    "27": "Voice, data and network cabling",
    "28": "Fire alarm, access control and surveillance",
    "31": "Excavation, grading and earth support",
    "32": "Paving, landscaping and site amenities",
    "33": "Site water, sewer, storm and power services",
    "34": "Rail, transit and transportation infrastructure",
    "35": "Marine, dredging and waterfront work",
    "40": "Industrial process piping and interconnections",
    "41": "Bulk material handling and processing plant",
    "42": "Industrial process thermal equipment",
    "43": "Industrial gas and liquid handling plant",
    "44": "Emissions, effluent and waste treatment plant",
    "45": "Industry-specific process equipment",
    "46": "Water and wastewater treatment plant",
    "48": "On-site power generation plant",
}


def _build_passage_text(payload: dict[str, Any]) -> str:
    """Synthesise a cross-encoder-ready passage from the snapshot payload.

    The synthesis goal: give BGE-M3 a sentence that reads like an
    estimator's one-line description of the rate. Format:

        {collection_name}, {material_class}, {ifc_class},
        {category_type}, {installation_method}, {construction_stage},
        {ost_category}, {uniformat_group}, {unit_type} ({rate_unit}),
        {MasterFormat label}, {csi_division}.

    Synthesis rules:
    - Empty/None fields are skipped (no em-dash spam).
    - ALL-CAPS fields title-cased.
    - PascalCase / CamelCase identifier-style strings (``ReinforcedConcrete``,
      ``IfcSlab``, ``OST_Walls``) split on capital boundaries so BGE-M3's
      sparse channel sees discrete word tokens.
    - ``masterformat_division`` is mapped to its human label
      (``"03 30 00"`` → ``"MasterFormat 03 30 00 Concrete"``) so the
      cross-encoder picks up the discipline keyword.
    - Field order is "most semantic first" so an early-truncated passage
      still carries the strongest signal (BGE encoder defaults truncate
      at 8192 tokens; we're nowhere near that, but the order is good
      practice).
    """
    parts: list[str] = []

    # 1. The collection name is the most natural-language field — it's
    #    typically a noun phrase like "Stucco work", "Internal piping",
    #    "Monolithic concrete and reinforced concrete structures". Lead
    #    with it so cosine similarity anchors on the topic.
    collection = _normalise_text(payload.get("collection_name"))
    if collection:
        parts.append(collection)

    # 2. Material — split CamelCase so "Reinforced Concrete" gives BGE
    #    real lexical tokens, not "ReinforcedConcrete" as a single OOV
    #    chunk.
    material = payload.get("material_class")
    if material:
        parts.append(_split_camelcase(str(material)))

    # 3. IFC class — split for the same reason. The estimator query
    #    typically uses "concrete wall IfcWall" structure, so we mirror
    #    it.
    ifc_class = payload.get("ifc_class")
    if ifc_class:
        parts.append(_split_camelcase(str(ifc_class)))

    # 4. IFC predefined type — adds specificity (USERDEFINED is noise;
    #    drop it). Only kept when it's an actual subtype string.
    ifc_subtype = payload.get("ifc_predefined_type")
    if ifc_subtype and str(ifc_subtype).upper() not in {"USERDEFINED", "NOTDEFINED"}:
        parts.append(_split_camelcase(str(ifc_subtype)))

    # 5. OST category — same split treatment, drop the OST_ prefix
    #    which is an authoring-tool-internal artefact (no semantic value).
    ost = payload.get("ost_category")
    if ost:
        ost_clean = str(ost).removeprefix("OST_")
        parts.append(_split_camelcase(ost_clean))

    # 6. Category type — typically an ALL-CAPS noun phrase like
    #    "CONSTRUCTION WORK", "EQUIPMENT INSTALLATION". Title-cased by
    #    _normalise_text.
    cat = _normalise_text(payload.get("category_type"))
    if cat:
        parts.append(cat)

    # 7. Installation method — narrows the "how" of the rate. CamelCase
    #    split for ``CastInPlace`` / ``Precast`` etc.
    inst = payload.get("installation_method")
    if inst:
        parts.append(_split_camelcase(str(inst)))

    # 8. Construction stage — ``"01_Foundation"`` is informative; the
    #    leading-digit prefix is a sort key, not user-facing. Strip it.
    #    Replace remaining underscores with spaces so multi-segment
    #    codes like ``"02_Special_Demo"`` read as natural words. Collapse
    #    runs of whitespace produced by the camelcase split + underscore
    #    replace (without this, ``"Special_Demo"`` → ``"Special  Demo"``).
    stage = payload.get("construction_stage")
    if stage:
        stage_clean = str(stage).split("_", 1)[-1] if "_" in str(stage) else str(stage)
        rendered = _split_camelcase(stage_clean.replace("_", " "))
        parts.append(" ".join(rendered.split()))

    # 9. Uniformat group — ``"A_Substructure"``-style codes. Same strip.
    uni = payload.get("uniformat_group")
    if uni:
        uni_clean = str(uni).split("_", 1)[-1] if "_" in str(uni) else str(uni)
        rendered = _split_camelcase(uni_clean.replace("_", " "))
        parts.append(" ".join(rendered.split()))

    # 10. Unit + unit_type — pair them so the encoder sees
    #     "Volume (100 CY)" / "Area (m2)" / "Linear (m)". The
    #     cross-encoder grounds on the unit family when the user query
    #     mentions m2 / m3 / kg / pcs.
    unit_type = payload.get("unit_type")
    rate_unit = payload.get("rate_unit")
    if unit_type and rate_unit:
        parts.append(f"{unit_type} ({rate_unit})")
    elif unit_type:
        parts.append(str(unit_type))
    elif rate_unit:
        parts.append(str(rate_unit))

    # 11. MasterFormat + label — discipline keyword. See _mf_label.
    mf = payload.get("masterformat_division")
    if mf:
        parts.append(_mf_label(str(mf)))

    # 12. CSI division — terse fallback when masterformat label is
    #     unknown. Skip when already covered by the MF label.
    csi = payload.get("csi_division_2")
    if csi and not mf:
        parts.append(f"CSI Division {csi}")

    # Dedup adjacent / repeated tokens. construction_stage and
    # uniformat_group commonly share suffixes after the digit/letter
    # prefix strip (``13_Sitework`` and ``G_Sitework`` both reduce to
    # "Sitework") which produces visible repetition in the passage.
    # Lowercase-key dedup so "Sitework" and "sitework" collapse to one.
    seen_keys: set[str] = set()
    deduped: list[str] = []
    for p in parts:
        if not p:
            continue
        key = p.strip().lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(p)

    return ". ".join(deduped)


def _build_description(passage_text: str) -> str:
    """The UI-facing description is the same synthesis as ``passage_text``.

    Kept as a separate field so future work can diverge them (e.g., a
    short UI label vs a long encoder passage). Today they're identical
    so the UI gets the same human-readable line the cross-encoder is
    scoring against — useful for debugging "why did this rank here?".
    """
    return passage_text


# ── Qdrant ingestion ─────────────────────────────────────────────────────


def _ensure_target_collection(
    client: QdrantClient,
    source: str,
    target: str,
) -> None:
    """Create ``target`` with the same vector schema as ``source``.

    Idempotent — if the target already exists, leave it alone (caller
    runs in resume mode by default; explicit ``--recreate`` to reset).
    Mirrors source's vector dims, distance, and sparse-vector schema
    one-for-one so future query-time code can fan dense+sparse exactly
    like the production adapter does.
    """
    try:
        info = client.get_collection(source)
    except Exception as exc:
        raise RuntimeError(f"source collection {source!r} doesn't exist or is unreachable: {exc}") from exc

    existing = {c.name for c in client.get_collections().collections}
    if target in existing:
        print(
            f"  [ensure] target collection {target!r} already exists — resume mode",
            flush=True,
        )
        return

    # Extract source vector schema. qdrant_client surfaces named vectors
    # via ``config.params.vectors`` (a dict for multi-vector collections).
    vectors_config = info.config.params.vectors
    sparse_vectors_config = info.config.params.sparse_vectors

    if isinstance(vectors_config, dict):
        vc_dict: dict[str, qmodels.VectorParams] = {}
        for name, vp in vectors_config.items():
            vc_dict[name] = qmodels.VectorParams(size=vp.size, distance=vp.distance)
        vectors_param: Any = vc_dict
    else:
        vp = vectors_config
        vectors_param = qmodels.VectorParams(size=vp.size, distance=vp.distance)

    sparse_param: dict[str, qmodels.SparseVectorParams] | None = None
    if isinstance(sparse_vectors_config, dict) and sparse_vectors_config:
        sparse_param = {name: qmodels.SparseVectorParams() for name in sparse_vectors_config}

    print(
        f"  [ensure] creating target {target!r} with vectors={list(vectors_param.keys())} "
        f"sparse={list(sparse_param.keys()) if sparse_param else 'none'}",
        flush=True,
    )
    client.create_collection(
        collection_name=target,
        vectors_config=vectors_param,
        sparse_vectors_config=sparse_param,
    )

    # Mirror the source's payload field indices so downstream search
    # ``_build_filter`` works without re-creating each index by hand.
    # We re-create every keyword/bool/integer index from the source
    # collection's ``payload_schema`` (introspected at runtime).
    schema = getattr(info, "payload_schema", {}) or {}
    for field_name, meta in schema.items():
        data_type = getattr(meta, "data_type", None) or (meta.get("data_type") if isinstance(meta, dict) else None)
        if not data_type:
            continue
        try:
            client.create_payload_index(
                collection_name=target,
                field_name=field_name,
                field_schema=str(data_type),
            )
        except Exception as exc:
            print(
                f"  [ensure] payload index {field_name} ({data_type}) skipped: {exc}",
                flush=True,
            )


def _existing_target_ids(client: QdrantClient, target: str) -> set[str]:
    """Return the set of point IDs already present in ``target``.

    Used for resume-mode: the build can be interrupted mid-run and a
    later invocation skips any IDs that already shipped. The set is
    bounded by the source collection's point count (~55K for English)
    so holding it in memory is cheap.
    """
    seen: set[str] = set()
    offset: Any = None
    while True:
        try:
            points, offset = client.scroll(
                collection_name=target,
                limit=2000,
                with_payload=False,
                with_vectors=False,
                offset=offset,
            )
        except Exception as exc:
            print(f"  [resume] scroll(target) failed (likely empty): {exc}", flush=True)
            return seen
        for p in points:
            seen.add(str(p.id))
        if offset is None:
            break
    return seen


def _load_encoder(model_name: str = "BAAI/bge-m3"):
    """Lazy-import and return the BGE-M3 model with FP32 weights."""
    print(f"  [encoder] loading {model_name} (FP32, ~2.3GB)…", flush=True)
    t0 = time.perf_counter()
    from FlagEmbedding import BGEM3FlagModel  # noqa: PLC0415

    model = BGEM3FlagModel(model_name, use_fp16=False)
    print(f"  [encoder] loaded in {time.perf_counter() - t0:.1f}s", flush=True)
    return model


def _encode_batch(model: Any, texts: list[str]) -> tuple[list[list[float]], list[Any]]:
    """Encode a batch and return (dense_vectors, sparse_vectors).

    Sparse vectors are returned as qdrant_client ``SparseVector`` instances
    ready to drop into ``PointStruct.vector``.
    """
    from qdrant_client.http.models import SparseVector  # noqa: PLC0415

    out = model.encode(
        texts,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    dense = [list(map(float, v)) for v in out["dense_vecs"]]
    sparse = []
    for weight_map in out["lexical_weights"]:
        indices = [int(k) for k in weight_map]
        values = [float(v) for v in weight_map.values()]
        sparse.append(SparseVector(indices=indices, values=values))
    return dense, sparse


def build_enriched_snapshot(
    *,
    qdrant_url: str = "http://localhost:6333",
    source: str = "cwicr_en_v3",
    target: str = "cwicr_en_v3_enriched",
    batch_size: int = 32,
    upsert_batch_size: int = 100,
    limit: int | None = None,
    dry_run: bool = False,
    recreate: bool = False,
    progress_every: int = 200,
) -> dict[str, Any]:
    """Run the full enrichment pipeline. Returns a summary dict.

    ``limit`` caps how many *new* points to encode this run. Resume-mode
    semantics: the cap is "encode N more points beyond what's already
    in the target" rather than "process the first N source points" so a
    second invocation with the same ``--limit`` extends coverage rather
    than re-doing work.

    ``dry_run`` is non-destructive: skips collection creation, skips the
    encoder load (no GPU/CPU spend), prints the first 3 synthesised
    passages so the operator can sanity-check the synthesis rules.
    """
    started = time.perf_counter()
    client = QdrantClient(url=qdrant_url, timeout=600)

    if dry_run:
        print(f"  [dry-run] scrolling first 3 points from {source!r}", flush=True)
        points, _ = client.scroll(
            collection_name=source,
            limit=3,
            with_payload=True,
            with_vectors=False,
        )
        previews = []
        for p in points:
            passage = _build_passage_text(p.payload or {})
            previews.append(
                {
                    "id": str(p.id),
                    "rate_code": (p.payload or {}).get("rate_code"),
                    "passage_text": passage,
                }
            )
            print(
                f"    {p.id} ({(p.payload or {}).get('rate_code')!r}): {passage}",
                flush=True,
            )
        return {
            "mode": "dry-run",
            "source": source,
            "previews": previews,
            "took_s": round(time.perf_counter() - started, 1),
        }

    if recreate:
        try:
            client.delete_collection(target)
            print(f"  [recreate] dropped existing {target!r}", flush=True)
        except Exception as exc:
            print(
                f"  [recreate] delete skipped (collection may not exist): {exc}",
                flush=True,
            )

    _ensure_target_collection(client, source, target)

    print("  [resume] scanning target for already-written IDs…", flush=True)
    skip_ids = _existing_target_ids(client, target)
    print(f"  [resume] {len(skip_ids)} points already in target", flush=True)

    model = _load_encoder()

    # Scroll-and-encode loop. Source scrolling uses a 256-point page so
    # batches divide cleanly into multiple encoder batches.
    SOURCE_PAGE = 256
    encoded = 0
    encode_failures = 0
    total_seen = 0
    pending_passages: list[str] = []
    pending_payloads: list[dict[str, Any]] = []
    pending_ids: list[str] = []
    offset: Any = None

    def _flush() -> None:
        """Encode the pending batch and upsert into the target."""
        nonlocal encoded, encode_failures
        if not pending_passages:
            return
        try:
            dense, sparse = _encode_batch(model, pending_passages)
        except Exception as exc:
            print(
                f"  [encode] batch failed ({exc}); skipping {len(pending_passages)}",
                flush=True,
            )
            encode_failures += len(pending_passages)
            pending_passages.clear()
            pending_payloads.clear()
            pending_ids.clear()
            return

        points = []
        for pid, payload, passage, d, s in zip(
            pending_ids,
            pending_payloads,
            pending_passages,
            dense,
            sparse,
            strict=False,
        ):
            new_payload = dict(payload)
            new_payload["description"] = _build_description(passage)
            new_payload["passage_text"] = passage
            points.append(
                qmodels.PointStruct(
                    id=pid,
                    vector={"dense": d, "sparse": s},
                    payload=new_payload,
                )
            )

        for chunk_start in range(0, len(points), upsert_batch_size):
            chunk = points[chunk_start : chunk_start + upsert_batch_size]
            try:
                client.upsert(collection_name=target, points=chunk, wait=False)
                encoded += len(chunk)
            except Exception as exc:
                print(f"  [upsert] chunk failed ({exc})", flush=True)
                encode_failures += len(chunk)
        pending_passages.clear()
        pending_payloads.clear()
        pending_ids.clear()

    print(
        f"  [encode] starting scroll on {source!r} (batch={batch_size}, limit={limit})",
        flush=True,
    )
    while True:
        try:
            points, offset = client.scroll(
                collection_name=source,
                limit=SOURCE_PAGE,
                with_payload=True,
                with_vectors=False,
                offset=offset,
            )
        except Exception as exc:
            print(f"  [encode] scroll failed: {exc}", flush=True)
            break

        if not points:
            break

        for p in points:
            total_seen += 1
            pid = str(p.id)
            if pid in skip_ids:
                continue
            payload = p.payload or {}
            passage = _build_passage_text(payload)
            if not passage:
                # No descriptive fields populated — fall back to the
                # rate_code so the encoder still produces SOME vector
                # rather than choking on an empty string.
                passage = str(payload.get("rate_code") or pid)

            pending_passages.append(passage)
            pending_payloads.append(payload)
            pending_ids.append(pid)

            if len(pending_passages) >= batch_size:
                _flush()
                if encoded and encoded % progress_every == 0:
                    elapsed = time.perf_counter() - started
                    rate = encoded / elapsed if elapsed > 0 else 0
                    print(
                        f"  [encode] {encoded} done / {total_seen} seen ({rate:.1f} pt/s, elapsed {elapsed:.0f}s)",
                        flush=True,
                    )

            if limit is not None and encoded + len(pending_passages) >= limit:
                # Hit the per-run cap. Drain pending then stop.
                _flush()
                offset = None
                break

        if limit is not None and encoded >= limit:
            break

        if offset is None:
            break

    # Drain anything still pending.
    _flush()

    took_s = time.perf_counter() - started
    summary = {
        "source": source,
        "target": target,
        "encoded": encoded,
        "skipped_resume": len(skip_ids),
        "total_seen": total_seen,
        "encode_failures": encode_failures,
        "took_s": round(took_s, 1),
        "rate_pt_per_s": round(encoded / took_s, 2) if took_s > 0 else 0,
    }
    print(f"\n  [done] {json.dumps(summary)}", flush=True)
    return summary


# ── CLI ──────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument("--source", default="cwicr_en_v3")
    parser.add_argument("--target", default="cwicr_en_v3_enriched")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--upsert-batch-size", type=int, default=100)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap on points to encode this run (default: all). Resume-aware — already-encoded points are skipped.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="DROP and recreate the target collection before ingest.",
    )
    parser.add_argument("--progress-every", type=int, default=200)
    parser.add_argument(
        "--write-summary",
        type=Path,
        default=None,
        help="Write the summary JSON to this path on completion.",
    )
    args = parser.parse_args(argv)

    summary = build_enriched_snapshot(
        qdrant_url=args.qdrant_url,
        source=args.source,
        target=args.target,
        batch_size=args.batch_size,
        upsert_batch_size=args.upsert_batch_size,
        limit=args.limit,
        dry_run=args.dry_run,
        recreate=args.recreate,
        progress_every=args.progress_every,
    )
    if args.write_summary:
        args.write_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
