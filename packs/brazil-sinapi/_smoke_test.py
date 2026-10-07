"""Smoke test for the brazil-sinapi partner pack (run manually).

Validates:
  * manifest imports + pydantic-validates
  * all rule_packs/*.json parse cleanly and match the manifest list
  * pt-BR locale parses
  * onboarding.yaml parses
  * logo.svg is well-formed XML

Usage (from repo root, paths are deliberately not escape sequences):
    set PYTHONPATH=backend;packs/brazil-sinapi/src
    python packs/brazil-sinapi/_smoke_test.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import xml.etree.ElementTree as ET

import yaml

from openconstructionerp_brazil_sinapi import MANIFEST


def main() -> int:
    print("MANIFEST OK")
    print("  slug                 =", MANIFEST.slug)
    print("  partner_name         =", MANIFEST.partner_name)
    print("  pack_version         =", MANIFEST.pack_version)
    print("  default_locale       =", MANIFEST.default_locale)
    print("  default_currency     =", MANIFEST.default_currency)
    print("  default_tax_template =", MANIFEST.default_tax_template)
    print("  cwicr_regions        =", MANIFEST.cwicr_regions)
    print("  rule_packs           =", MANIFEST.validation_rule_packs)
    print("  metadata.country     =", MANIFEST.metadata.get("country"))
    print("  metadata.metros      =", len(MANIFEST.metadata.get("preferred_metros", [])))
    print("  primary_color        =", MANIFEST.branding.primary_color)
    print("  accent_color         =", MANIFEST.branding.accent_color)
    print("  effective_powered_by =", MANIFEST.effective_powered_by)

    pub = MANIFEST.to_public_dict()
    print("to_public_dict OK      ; rule_pack count =", len(pub["validation_rule_packs"]))

    pack_root = pathlib.Path(__file__).parent / "src" / "openconstructionerp_brazil_sinapi"
    rp_dir = pack_root / "rule_packs"
    expected = set(MANIFEST.validation_rule_packs)
    shipped: set[str] = set()
    for f in sorted(rp_dir.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        rp_id = data["rule_pack_id"]
        n = len(data.get("enables_rule_ids", []))
        shipped.add(rp_id)
        print(f"  rule_pack {rp_id:24s} {n:2d} rules    ({f.name})")

    missing = expected - shipped
    extra = shipped - expected
    if missing:
        print("MISSING rule pack files for manifest slugs:", missing)
        return 1
    if extra:
        print("WARN extra rule pack files not referenced from manifest:", extra)

    loc_text = (pack_root / "locales" / "pt-BR.json").read_text(encoding="utf-8")
    loc = json.loads(loc_text)
    keys = len(loc["translation"])
    cov = loc["_meta"]["coverage"]
    print(f"  locale pt-BR         keys = {keys}  coverage = {cov}")

    ob = yaml.safe_load((pack_root / "onboarding.yaml").read_text(encoding="utf-8"))
    print(f"  onboarding           version = {ob['version']}  steps = {len(ob['steps'])}")

    ET.fromstring((pack_root / "logo.svg").read_text(encoding="utf-8"))
    print("  logo.svg             well-formed XML")

    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
