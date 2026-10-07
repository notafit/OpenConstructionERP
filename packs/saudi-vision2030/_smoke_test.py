"""Smoke test for the saudi-vision2030 partner pack (run manually).

Validates:
  * manifest imports + pydantic-validates
  * all rule_packs/*.json parse cleanly and 1:1 match the manifest list
  * ar.json locale parses and has RTL direction set
  * onboarding.yaml parses, has rtl direction, all steps have bilingual titles
  * logo.svg is well-formed XML
  * no LTR-only hard-coded text trap that breaks under RTL mirroring

Usage (from repo root, paths are deliberately not escape sequences):
    set PYTHONPATH=backend;packs/saudi-vision2030/src
    python packs/saudi-vision2030/_smoke_test.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import xml.etree.ElementTree as ET

import yaml

from openconstructionerp_saudi_vision2030 import MANIFEST


def main() -> int:
    print("MANIFEST OK")
    print("  slug                 =", MANIFEST.slug)
    print("  partner_name         =", MANIFEST.partner_name)
    print("  pack_version         =", MANIFEST.pack_version)
    print("  default_locale       =", MANIFEST.default_locale)
    print("  default_currency     =", MANIFEST.default_currency)
    print("  default_tax_template =", MANIFEST.default_tax_template)
    print("  cwicr_regions        =", MANIFEST.cwicr_regions)
    print(
        "  rule_packs (n=%d)    = %s"
        % (
            len(MANIFEST.validation_rule_packs),
            MANIFEST.validation_rule_packs,
        )
    )
    print("  metadata.country     =", MANIFEST.metadata.get("country"))
    print("  metadata.direction   =", MANIFEST.metadata.get("writing_direction"))
    print("  primary_color        =", MANIFEST.branding.primary_color)
    print("  accent_color         =", MANIFEST.branding.accent_color)
    print("  effective_powered_by =", MANIFEST.effective_powered_by)

    pub = MANIFEST.to_public_dict()
    print("to_public_dict OK      ; rule_pack count =", len(pub["validation_rule_packs"]))

    pack_root = pathlib.Path(__file__).parent / "src" / "openconstructionerp_saudi_vision2030"
    rp_dir = pack_root / "rule_packs"
    expected = set(MANIFEST.validation_rule_packs)
    shipped: set[str] = set()
    for f in sorted(rp_dir.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        rp_id = data["rule_pack_id"]
        n = len(data.get("enables_rule_ids", []))
        shipped.add(rp_id)
        # Require a Saudi-English description and at least one Arabic field
        # so packs cannot silently degrade to LTR-only metadata.
        assert "description" in data, f"{f.name}: description missing"
        assert "name_ar" in data, f"{f.name}: name_ar missing (RTL safety)"
        print(f"  rule_pack {rp_id:30s} {n:2d} rules    ({f.name})")

    missing = expected - shipped
    extra = shipped - expected
    if missing:
        print("MISSING rule pack files for manifest slugs:", missing)
        return 1
    if extra:
        print("ERROR extra rule pack files not referenced from manifest:", extra)
        return 1

    # ---- locale ----
    loc_text = (pack_root / "locales" / "ar.json").read_text(encoding="utf-8")
    loc = json.loads(loc_text)
    assert loc["_meta"]["direction"] == "rtl", "ar.json must declare direction=rtl"
    assert loc["_meta"]["locale"] == "ar", "ar.json must declare locale=ar"
    keys = len(loc["translation"])
    cov = loc["_meta"]["coverage"]
    print(f"  locale ar            keys = {keys}  direction = rtl  coverage = {cov[:60]}...")
    assert keys >= 60, f"ar.json needs >=60 high-traffic keys for partner pack, got {keys}"

    # ---- onboarding ----
    ob = yaml.safe_load((pack_root / "onboarding.yaml").read_text(encoding="utf-8"))
    assert ob.get("direction") == "rtl", "onboarding.yaml must declare direction=rtl"
    print(f"  onboarding           version = {ob['version']}  steps = {len(ob['steps'])}  direction = rtl")
    for st in ob["steps"]:
        t = st.get("title_i18n", {})
        assert "ar" in t and "en" in t, f"step {st['id']}: title_i18n missing ar or en"

    # ---- logo ----
    logo_xml = (pack_root / "logo.svg").read_text(encoding="utf-8")
    ET.fromstring(logo_xml)
    # RTL-safety probe: must contain an Arabic glyph in the wordmark and
    # a direction="rtl" attribute on the primary text element.
    assert 'direction="rtl"' in logo_xml, "logo.svg primary text must set direction=rtl"
    assert "حزمة" in logo_xml or "السعودية" in logo_xml, "logo.svg must contain Arabic primary wordmark for RTL safety"
    print("  logo.svg             well-formed XML, contains Arabic + direction=rtl")

    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
