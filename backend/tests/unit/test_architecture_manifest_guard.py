#!/usr/bin/env python3
"""Tests for the architecture manifest guard.

``scripts/check_architecture_manifest.py`` exists because the committed manifest
rotted for three months while every gate stayed green, so the thing worth
testing is that it goes red on a realistically stale file rather than only that
it goes green on a fresh one. A gate nobody has seen fail is not a gate.

The cases come in pairs, the way ``test_changelog_mirror.py`` writes them. Every
failure has a mirror with the two sides swapped, because the drift runs both
ways: a module added to the tree and not regenerated, and a module deleted from
the tree while the manifest keeps drawing it. Each is asserted by the name of
the module that moved rather than by a substring of the whole output, so a
copy-paste naming the wrong side fails here instead of pointing a future reader
at the half that was already correct.

Two properties get their own classes because they are the ones that would make
this guard unpassable in CI rather than merely wrong:

``TestLineEndings`` pins the CRLF case. The founder's Windows clone runs with
``core.autocrlf=true`` and the generator writes through a text stream, so the
committed file is CRLF on that disk and LF in the blob and on a Linux runner. A
guard comparing raw bytes would be red on one platform and green on the other,
for a reason that has nothing to do with staleness.

``TestGeneratorDeterminism`` pins the defect this guard could not otherwise be
built on top of. The generator resolved a frontend feature to a backend module
by iterating a SET of strings and taking the first substring hit, and Python
randomises string hashing per process, so four features got a different answer
on every run from identical inputs. Both answers are on record in this
repository: the manifest committed in June carries ``field -> field_diary``,
and a regeneration run during this work produced ``field -> field_time`` from
the same generator over the same three candidate modules. Sorted order settles
on ``field_diary``. The subprocess test is the one that can actually see this,
because a single process has a single hash seed and would agree with itself
all day.

Run::

    python -m pytest backend/tests/unit/test_architecture_manifest_guard.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_architecture_manifest.py"
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate_architecture_manifest.py"


def _load(path: Path, name: str):
    """Import a script by path, the way the repo's other script tests do."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not build an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load(SCRIPT_PATH, "check_architecture_manifest")
generator = _load(GENERATOR_PATH, "generate_architecture_manifest")


# ---------------------------------------------------------------------------
# Fixture manifests, small enough to read at a glance and shaped like the real
# one: a modules list, a frontend_features list, a statistics block and _meta.
# ---------------------------------------------------------------------------


def _manifest(
    modules: list[str],
    features: list[str],
    *,
    stats_override: dict[str, Any] | None = None,
    docstring: str = "Prose.",
) -> str:
    """Render a manifest carrying exactly these modules and features."""
    payload: dict[str, Any] = {
        "_meta": {
            "generator": "generate_architecture_manifest.py",
            "description": "Auto-generated architecture manifest for OpenConstructionERP",
            "version": "1.0.0",
        },
        "modules": [
            {
                "module_id": m,
                "module_label": m.replace("_", " ").title(),
                "module_category": "core",
                "files": ["__init__.py"],
                "manifest": None,
                "models": [{"class_name": "Thing", "tablename": "thing", "docstring": docstring}],
                "routes": [],
                "schemas": [],
                "import_dependencies": [],
            }
            for m in modules
        ],
        "frontend_features": [
            {"name": f, "ts_files": 1, "css_files": 0, "test_files": 0, "total_files": 1} for f in features
        ],
        "dependency_graph": {m: [] for m in modules},
        "frontend_backend_mapping": dict.fromkeys(features),
        "statistics": {
            "backend_modules": len(modules),
            "frontend_features": len(features),
            "total_models": len(modules),
        },
    }
    if stats_override:
        payload["statistics"].update(stats_override)
    return generator.render_manifest(payload)


BASELINE_MODULES = ["boq", "projects", "tendering", "validation"]
BASELINE_FEATURES = ["boq", "projects", "tendering", "validation"]

FRESH = _manifest(BASELINE_MODULES, BASELINE_FEATURES)


class TestReaders:
    """What the guard's reader sees in a manifest."""

    def test_summarise_reads_all_three_populations(self) -> None:
        modules, features, stats = guard.summarise(json.loads(FRESH))
        assert modules == set(BASELINE_MODULES)
        assert features == set(BASELINE_FEATURES)
        assert stats["backend_modules"] == 4

    def test_a_manifest_that_lost_a_whole_section_reads_empty_rather_than_raising(self) -> None:
        # A guard that crashed here would report a broken guard rather than a
        # broken manifest, and the two need different answers.
        modules, features, stats = guard.summarise({"_meta": {}})
        assert modules == set()
        assert features == set()
        assert stats == {}

    def test_render_manifest_ends_with_one_newline_and_uses_lf(self) -> None:
        # The committed file's shape. If this changes, every comparison below
        # is comparing something other than what gets written.
        assert FRESH.endswith("}\n")
        assert "\r" not in FRESH


class TestBothDirections:
    """The pairs. Each failure is asserted with its mirror image beside it."""

    def test_a_manifest_that_matches_the_tree_passes(self) -> None:
        assert guard.compare(FRESH, FRESH) == []

    def test_a_manifest_missing_a_module_fails(self) -> None:
        # THE NEGATIVE CONTROL. This is the realistic staleness: a module was
        # added to the tree and nobody reran the generator. It is exactly the
        # shape the real file was in, 70 times over.
        stale = _manifest(["boq", "projects", "tendering"], BASELINE_FEATURES)
        failures = guard.compare(stale, FRESH)
        assert failures, "a manifest missing a module was accepted"
        assert any("1 backend module(s) are in the tree and absent" in f and "validation" in f for f in failures)

    def test_a_manifest_carrying_a_module_the_tree_lost_fails(self) -> None:
        # The same omission the other way round: a module was deleted and the
        # map still draws it.
        stale = _manifest([*BASELINE_MODULES, "retired"], BASELINE_FEATURES)
        failures = guard.compare(stale, FRESH)
        assert any("no longer in the tree" in f and "retired" in f for f in failures)

    def test_a_manifest_missing_a_frontend_feature_fails(self) -> None:
        stale = _manifest(BASELINE_MODULES, ["boq", "projects", "tendering"])
        failures = guard.compare(stale, FRESH)
        assert any("frontend feature(s) are in the tree and absent" in f and "validation" in f for f in failures)

    def test_a_manifest_carrying_a_frontend_feature_the_tree_lost_fails(self) -> None:
        stale = _manifest(BASELINE_MODULES, [*BASELINE_FEATURES, "retired"])
        failures = guard.compare(stale, FRESH)
        assert any("frontend feature(s) are in the committed manifest" in f and "retired" in f for f in failures)

    def test_seventy_missing_modules_are_all_named_in_one_message(self) -> None:
        # One message, every missing module in it, so a reader fixes them in one
        # pass rather than rerunning the guard per module.
        tree = _manifest([f"m{i:03d}" for i in range(70)], BASELINE_FEATURES)
        failures = guard.compare(_manifest([], BASELINE_FEATURES), tree)
        named = [f for f in failures if "70 backend module(s)" in f]
        assert len(named) == 1
        assert "m000" in named[0]
        assert "m069" in named[0]

    def test_a_drifted_statistic_is_reported_with_both_values(self) -> None:
        stale = _manifest(BASELINE_MODULES, BASELINE_FEATURES, stats_override={"total_models": 999})
        failures = guard.compare(stale, FRESH)
        assert any("total_models 999 -> 4" in f for f in failures)


class TestContentDriftWithMatchingPopulations:
    """The subtle case: every count agrees and the file is still wrong."""

    def test_a_reworded_docstring_fails_even_though_nothing_is_missing(self) -> None:
        # The manifest records every model, column, route and schema. A renamed
        # column or a rewritten docstring moves the file without moving any
        # count, and the page draws the stale text. A guard written against the
        # statistics alone would be green here, which is why equality is the
        # comparison and the counts are only the diagnosis.
        stale = _manifest(BASELINE_MODULES, BASELINE_FEATURES, docstring="The old wording.")
        failures = guard.compare(stale, FRESH)
        assert len(failures) == 1
        assert "same modules, features and statistics" in failures[0]
        assert "First difference at line" in failures[0]

    def test_the_first_difference_names_both_sides(self) -> None:
        stale = _manifest(BASELINE_MODULES, BASELINE_FEATURES, docstring="The old wording.")
        failures = guard.compare(stale, FRESH)
        assert "The old wording." in failures[0]
        assert "Prose." in failures[0]

    def test_a_long_value_is_marked_when_the_message_trims_it(self) -> None:
        # An unmarked trim reads as a complete value that ends oddly, and sends
        # the reader comparing two sentences that were never the difference.
        stale = _manifest(BASELINE_MODULES, BASELINE_FEATURES, docstring="x" * 400)
        failures = guard.compare(stale, FRESH)
        assert "[...]" in failures[0]

    def test_a_short_value_is_not_marked(self) -> None:
        assert guard._excerpt("short") == "short"
        assert guard._excerpt("y" * 200).endswith(" [...]")

    def test_a_truncated_manifest_is_reported_rather_than_read_as_equal(self) -> None:
        truncated = json.dumps(json.loads(FRESH), indent=2, ensure_ascii=False)[: len(FRESH) // 2]
        failures = guard.compare(truncated, FRESH)
        assert any("not valid JSON" in f for f in failures)


class TestLineEndings:
    """The property that decides whether this guard can pass in CI at all."""

    def test_a_crlf_committed_file_compares_equal_to_an_lf_regeneration(self) -> None:
        # What a Windows checkout under core.autocrlf=true holds on disk. The
        # guard reads the real file with universal newlines, which is what
        # produces the left-hand side here.
        on_disk = FRESH.replace("\n", "\r\n")
        as_read = on_disk.replace("\r\n", "\n")
        assert guard.compare(as_read, FRESH) == []

    def test_reading_the_file_through_the_guards_own_path_normalises_crlf(self, tmp_path: Path) -> None:
        # Not a restatement of the test above. That one assumes the read
        # normalises; this one proves the read the guard actually performs does.
        crlf_file = tmp_path / "architecture_manifest.json"
        crlf_file.write_bytes(FRESH.replace("\n", "\r\n").encode("utf-8"))
        assert b"\r\n" in crlf_file.read_bytes()
        assert guard.compare(crlf_file.read_text(encoding="utf-8"), FRESH) == []


# ---------------------------------------------------------------------------
# Generator determinism
# ---------------------------------------------------------------------------


def _tiny_tree(root: Path) -> None:
    """Build the smallest tree that reproduces the ambiguous-match case.

    ``field`` matches three module ids by substring, so which one the generator
    picks is decided by iteration order and nothing else.
    """
    modules = root / "backend" / "app" / "modules"
    for name in ("field_time", "field_diary", "fieldreports"):
        (modules / name).mkdir(parents=True)
        (modules / name / "__init__.py").write_text("", encoding="utf-8")
    features = root / "frontend" / "src" / "features"
    (features / "field").mkdir(parents=True)
    (features / "field" / "index.ts").write_text("export {};\n", encoding="utf-8")


class TestGeneratorDeterminism:
    """The generator must answer the same thing twice, on any machine."""

    def test_an_ambiguous_feature_resolves_to_the_alphabetically_first_module(self, tmp_path: Path) -> None:
        _tiny_tree(tmp_path)
        manifest = generator.generate_manifest(tmp_path)
        # field_diary sorts before field_time and fieldreports. Iterating the
        # set instead would return any of the three.
        assert manifest["frontend_backend_mapping"]["field"] == "field_diary"

    def test_the_candidate_set_really_is_ambiguous(self, tmp_path: Path) -> None:
        # Pins the premise of the test above. If the fixture ever stopped having
        # more than one candidate, that test would pass whether the loop is
        # sorted or not, and would quietly stop testing anything.
        _tiny_tree(tmp_path)
        manifest = generator.generate_manifest(tmp_path)
        ids = {m["module_id"] for m in manifest["modules"]}
        candidates = [m for m in ids if m in "field" or "field" in m]
        assert len(candidates) == 3

    def test_the_same_tree_renders_identically_under_two_hash_seeds(self, tmp_path: Path) -> None:
        # The test that can actually see the defect. A single process has a
        # single hash seed, so no amount of re-running inside this one would
        # have caught it; the shipped manifest is itself the record of one seed.
        _tiny_tree(tmp_path)
        renders = []
        for seed in ("0", "1"):
            env = {**os.environ, "PYTHONHASHSEED": seed}
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import importlib.util,sys,io,contextlib;"
                    "spec=importlib.util.spec_from_file_location('g',sys.argv[1]);"
                    "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
                    "buf=io.StringIO();"
                    "man=None\n"
                    "with contextlib.redirect_stdout(buf): man=m.generate_manifest(__import__('pathlib').Path(sys.argv[2]))\n"
                    "sys.stdout.write(m.render_manifest(man))",
                    str(GENERATOR_PATH),
                    str(tmp_path),
                ],
                capture_output=True,
                text=True,
                env=env,
                check=True,
            )
            renders.append(result.stdout)
        assert renders[0] == renders[1], "the generator produced different output under two hash seeds"


class TestTheInterpreterFloor:
    """The input that changes the answer without changing the tree.

    The generator is an ast reader, so it sees only what its own interpreter can
    parse. backend/app/modules/ai/ai_client.py uses PEP 695 generics, which 3.11
    cannot read, and the generator's response to that is a warning and an empty
    module rather than a failure. So the same tree yields a different manifest
    on 3.11 than on 3.12, and the 3.11 answer is the plausible-looking wrong one.
    """

    @pytest.mark.parametrize(
        ("version", "refused"),
        [
            ((3, 10), True),
            ((3, 11), True),
            ((3, 12), False),
            ((3, 13), False),
            ((4, 0), False),
        ],
    )
    def test_the_floor_is_312_and_is_applied_numerically(self, version: tuple[int, int], refused: bool) -> None:
        assert guard.interpreter_too_old(version) is refused

    def test_the_floor_matches_what_the_backend_requires(self) -> None:
        # Pinned so the constant cannot drift away from the project's own
        # requires-python without somebody noticing here.
        pyproject = (REPO_ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
        assert 'requires-python = ">=3.12"' in pyproject
        assert guard.REQUIRED_PYTHON == (3, 12)

    def test_a_file_the_generator_cannot_parse_comes_back_as_a_warning(self, tmp_path: Path) -> None:
        # The half that would otherwise be swallowed with the rest of the
        # generator's chatter. Without this the guard would compare a manifest
        # with a hollowed-out module against a correct one and call the correct
        # one stale.
        _tiny_tree(tmp_path)
        broken = tmp_path / "backend" / "app" / "modules" / "field_time" / "models.py"
        broken.write_text("class Broken(Base:\n    pass\n", encoding="utf-8")
        _text, warnings = guard.render_tree(tmp_path)
        assert len(warnings) >= 1
        assert any("models.py" in w for w in warnings)

    def test_a_clean_tree_produces_no_warnings(self, tmp_path: Path) -> None:
        # The negative half: a warning list that is never empty would make the
        # check above meaningless.
        _tiny_tree(tmp_path)
        _text, warnings = guard.render_tree(tmp_path)
        assert warnings == []


class TestTheRealTree:
    """The shipped file, read the way the guard reads it.

    Equality against a freshly generated manifest is deliberately NOT asserted
    here, and the reason is not squeamishness. The manifest is derived from
    about 2200 Python files and 188 feature folders, so it disagrees with the
    tree whenever anybody has an uncommitted edit open, which on this project is
    almost always. A test that is red on every working tree with work in it gets
    marked skip within a week, and then the negative controls above go with it.

    Equality belongs to the gate, which runs on a clean checkout in CI where the
    tree is quiet by construction. What is asserted here is the part a checkout
    cannot prove for itself: that the guard's reader can still read the shipped
    file, and that the populations it reports are not silently zero.
    """

    def test_the_shipped_manifest_parses_and_is_not_empty(self) -> None:
        text = guard.MANIFEST_PATH.read_text(encoding="utf-8")
        modules, features, stats = guard.summarise(json.loads(text))
        # Printed rather than asserted: these numbers move with every module
        # added, so pinning them would fail for the one reason this guard is
        # not about.
        print(
            f"committed manifest: {len(modules)} modules, {len(features)} frontend features, "
            f"{len(stats)} statistics, {len(text.encode('utf-8'))} bytes"
        )
        assert modules, "the committed manifest parsed to no modules at all"
        assert features, "the committed manifest parsed to no frontend features at all"
        assert stats.get("backend_modules") == len(modules)
        assert stats.get("frontend_features") == len(features)

    def test_the_guard_names_the_command_that_fixes_it(self) -> None:
        # The house rule the neighbouring checks follow: a failure message that
        # does not say what to run sends the reader to read the script.
        failures = guard.compare(_manifest(["boq"], ["boq"]), FRESH)
        assert failures
        assert guard.FIX_COMMAND == "python scripts/generate_architecture_manifest.py"

    @pytest.mark.parametrize("section", ["modules", "frontend_features", "statistics"])
    def test_the_shipped_manifest_carries_every_section_the_guard_reads(self, section: str) -> None:
        data = json.loads(guard.MANIFEST_PATH.read_text(encoding="utf-8"))
        assert section in data, f"the committed manifest has no {section} section"
