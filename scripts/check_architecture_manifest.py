#!/usr/bin/env python3
"""Architecture manifest guard: the committed map must be what the generator produces.

``frontend/src/features/architecture/architecture_manifest.json`` is a tracked,
shipped file. The Architecture Map page renders it, either from
``GET /api/v1/architecture_map/`` (which reads that same file off disk) or, when the
API is unreachable, by importing the JSON directly. Nothing builds it at request
time. So whatever is committed is what a reader sees.

It is produced by ``scripts/generate_architecture_manifest.py``, and until this
guard nothing ran that generator. Not a workflow, not the Makefile, not another
script, not a pre-commit hook. It ran when a person remembered, and people stop
remembering.

What that cost, measured on 2026-09-20: the committed manifest described 125
backend modules and 112 frontend features. The tree held 195 and 188. The
missing 70 modules were not a curated omission; the manifest was simply last
regenerated on 2026-06-11 in 09a09425c, when the repository really did hold
exactly 125 and 112, and the seven commits that touched the file since were
brand-name sweeps of two to four lines each. Every gate in the tree stayed green
across three months of drift, because a stale JSON file is still valid JSON that
still parses, still imports and still renders. The page was confidently showing
a system two thirds the size of the one it claims to describe.

What this reads:

  * the committed manifest, parsed as JSON
  * the manifest the generator produces from the current tree, rendered through
    the generator's own ``render_manifest`` so the two sides cannot disagree
    about formatting alone

What it fails on:

  * a module directory in the tree that the committed manifest does not carry,
    which is the rot this exists for
  * a module in the committed manifest that is no longer in the tree
  * the same two, for frontend feature directories
  * any statistic that disagrees
  * any remaining byte of difference once those agree, because the manifest
    carries every model, column, route and schema and all of it is what the page
    draws

Why equality and not a count. The statistics block is the part that looks like
the answer and is the part least able to give it. ``frontend_backend_mapped``
counts how many features resolved to SOME module, so it held steady at 168 while
the generator handed four of them a different module on every run; see the
sorted() note in the generator. A guard written against the counts alone would
have been green over both defects at once.

On ``_meta``: it carries ``generator``, ``description`` and a hand-set
``version`` of 1.0.0, and nothing about the machine or the moment the scan ran.
There is no timestamp, no hostname and no absolute path anywhere in the output.
So it is compared like everything else rather than excluded, and it has to be:
excluding a block is how a field that later starts carrying a timestamp stops
being noticed.

On line endings, which is the way a guard like this usually becomes unpassable
in CI. The generator writes through a text stream with no ``newline=``, so it
produces CRLF on Windows and LF on Linux, and the founder's Windows clone runs
with ``core.autocrlf=true``. A raw byte comparison would therefore fail on one
platform or the other for a reason that has nothing to do with staleness. This
reads the committed file with universal newlines, which normalises CRLF to LF,
and compares it against a string built in memory, which is LF by construction.
Both platforms get the same verdict, and so does a clone configured the other
way round.

Needs Python 3.12 or newer, and refuses rather than guessing below it. The
generator reads the tree with ``ast``, the backend is written to PEP 695, and on
3.11 an ``async def f[T](...)`` does not raise: the generator warns to a stdout
nobody reads and hands back a module with no models, routes or schemas. A guard
running there would report perfectly fresh commits as drifted and blame the
modules it had itself failed to read.

Exit codes:
    0  - the committed manifest is what the generator produces
    1  - it is not, either side could not be read, or the interpreter is too old

Usage::

    python scripts/check_architecture_manifest.py

Run from anywhere. Paths resolve relative to the repo root, one level up from
this file.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

MANIFEST_PATH = REPO_ROOT / "frontend" / "src" / "features" / "architecture" / "architecture_manifest.json"
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate_architecture_manifest.py"

# The command that fixes every failure this guard can report. Named in one
# place so the message and the workflow comment cannot drift apart.
FIX_COMMAND = "python scripts/generate_architecture_manifest.py"

# The generator is an AST reader, so it can only see what its own interpreter
# can parse, and the backend is written to PEP 695. On 3.11 the generator does
# not fail on `async def f[T](...)`: it prints a warning to a stdout nobody
# reads and returns a module entry with empty models, routes and schemas. The
# manifest that comes out is well-formed, plausible and missing the contents of
# whole modules.
#
# That makes this the one input that changes the answer without changing the
# tree. A guard running here would report the committed file as drifted and name
# the modules it had itself failed to read, which is a gate being confidently
# wrong rather than merely red. backend/pyproject.toml requires >= 3.12 and the
# workflow sets 3.12, so refusing below that costs nothing and removes the case.
REQUIRED_PYTHON = (3, 12)


def interpreter_too_old(version: tuple[int, ...] = sys.version_info[:2]) -> bool:
    """Return True when this interpreter cannot parse the code the generator reads."""
    return tuple(version[:2]) < REQUIRED_PYTHON


def load_generator(path: Path = GENERATOR_PATH):
    """Import the generator by path, the way the repo's other script tests do.

    Args:
        path: Location of generate_architecture_manifest.py.

    Returns:
        The imported module.

    Raises:
        AssertionError: When the file cannot be turned into an import spec.
    """
    spec = importlib.util.spec_from_file_location("generate_architecture_manifest", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not build an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_tree(root: Path = REPO_ROOT) -> tuple[str, list[str]]:
    """Return the manifest text for the tree at ``root``, and any parse warnings.

    The generator narrates every module it scans to stdout, which would bury
    this guard's own verdict, so that chatter is swallowed. Nothing is written
    to disk: the manifest is built in memory and serialised through the
    generator's own ``render_manifest``.

    The warnings are pulled back out of that swallowed chatter rather than
    dropped with it. A file the generator cannot parse does not stop it; the
    module lands in the manifest with empty models, routes and schemas, and the
    only trace is a line on a stream this function is in the middle of
    discarding. Returning them is what lets the caller tell "the manifest is
    stale" from "the manifest is missing the parts I could not read".
    """
    generator = load_generator()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        manifest = generator.generate_manifest(root)
    warnings = [line.strip() for line in buffer.getvalue().splitlines() if "[WARN]" in line]
    return generator.render_manifest(manifest), warnings


def summarise(manifest: dict[str, Any]) -> tuple[set[str], set[str], dict[str, Any]]:
    """Return the module ids, the frontend feature names and the statistics block.

    Args:
        manifest: A parsed architecture manifest.

    Returns:
        A tuple of module ids, frontend feature names and the statistics dict.
        Missing or malformed sections come back empty rather than raising, so a
        manifest that has lost a whole section is reported by the comparison
        below instead of crashing the guard.
    """
    modules = manifest.get("modules")
    module_ids = (
        {m["module_id"] for m in modules if isinstance(m, dict) and "module_id" in m}
        if isinstance(modules, list)
        else set()
    )

    features = manifest.get("frontend_features")
    feature_names = (
        {f["name"] for f in features if isinstance(f, dict) and "name" in f} if isinstance(features, list) else set()
    )

    statistics = manifest.get("statistics")
    if not isinstance(statistics, dict):
        statistics = {}

    return module_ids, feature_names, statistics


def _name_list(names: set[str]) -> str:
    """Render a set of names for a failure message, alphabetically."""
    return ", ".join(sorted(names))


def _excerpt(line: str, limit: int = 160) -> str:
    """Trim a manifest line for a failure message, marking it when it was cut.

    The manifest carries whole docstrings, so an untrimmed line can run to
    several hundred characters and bury the rest of the message. An unmarked
    trim is worse than a long line: it reads as a complete value that happens to
    end oddly, and the reader compares two sentences that were never the
    difference.
    """
    stripped = line.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + " [...]"


def _first_difference(committed_text: str, regenerated_text: str) -> str | None:
    """Return a description of the first differing line, or None when equal."""
    if committed_text == regenerated_text:
        return None
    committed_lines = committed_text.splitlines()
    regenerated_lines = regenerated_text.splitlines()
    # strict=False on purpose: a truncated or overlong manifest is one of the
    # cases this reports, and the tail is described below rather than raised.
    for index, (left, right) in enumerate(zip(committed_lines, regenerated_lines, strict=False), start=1):
        if left != right:
            return f"line {index}\n           committed:   {_excerpt(left)}\n           regenerated: {_excerpt(right)}"
    shorter, longer = sorted((len(committed_lines), len(regenerated_lines)))
    side = "committed" if len(committed_lines) < len(regenerated_lines) else "regenerated"
    return f"line {shorter + 1}, where the {side} file ends and the other runs on to line {longer}"


def compare(committed_text: str, regenerated_text: str) -> list[str]:
    """Return one message per way the committed manifest differs from the tree.

    Args:
        committed_text: Contents of the committed manifest, read with universal
            newlines so a CRLF checkout compares equal to an LF one.
        regenerated_text: What the generator produces from the tree right now.

    Returns:
        An empty list when the two agree exactly, otherwise one message per
        failure, ordered so the population differences a reader can act on come
        before the content difference that is usually their consequence.
    """
    failures: list[str] = []

    try:
        committed = json.loads(committed_text)
    except json.JSONDecodeError as exc:
        return [
            f"[FAIL] the committed manifest is not valid JSON ({exc}). The page renders this file "
            f"directly, so it does not merely fail this guard, it fails the reader. Rebuild it with "
            f"`{FIX_COMMAND}`"
        ]

    try:
        regenerated = json.loads(regenerated_text)
    except json.JSONDecodeError as exc:
        return [
            f"[FAIL] the generator produced text that is not valid JSON ({exc}). That is a defect in "
            f"scripts/generate_architecture_manifest.py rather than in the committed file"
        ]

    if committed_text == regenerated_text:
        return []

    committed_modules, committed_features, committed_stats = summarise(committed)
    tree_modules, tree_features, tree_stats = summarise(regenerated)

    missing_modules = tree_modules - committed_modules
    if missing_modules:
        failures.append(
            f"[FAIL] {len(missing_modules)} backend module(s) are in the tree and absent from the "
            f"committed manifest: {_name_list(missing_modules)}. The Architecture Map does not draw "
            f"them, and nothing else in the product reports their absence"
        )

    stale_modules = committed_modules - tree_modules
    if stale_modules:
        failures.append(
            f"[FAIL] {len(stale_modules)} backend module(s) are in the committed manifest and no "
            f"longer in the tree: {_name_list(stale_modules)}. The map draws modules that do not "
            f"exist, which is the quieter half of the same drift"
        )

    missing_features = tree_features - committed_features
    if missing_features:
        failures.append(
            f"[FAIL] {len(missing_features)} frontend feature(s) are in the tree and absent from the "
            f"committed manifest: {_name_list(missing_features)}"
        )

    stale_features = committed_features - tree_features
    if stale_features:
        failures.append(
            f"[FAIL] {len(stale_features)} frontend feature(s) are in the committed manifest and no "
            f"longer in the tree: {_name_list(stale_features)}"
        )

    drifted = sorted(
        key for key in set(committed_stats) | set(tree_stats) if committed_stats.get(key) != tree_stats.get(key)
    )
    if drifted:
        rows = ", ".join(f"{key} {committed_stats.get(key)} -> {tree_stats.get(key)}" for key in drifted)
        failures.append(f"[FAIL] {len(drifted)} statistic(s) disagree with the tree: {rows}")

    if not failures:
        where = _first_difference(committed_text, regenerated_text)
        failures.append(
            f"[FAIL] the committed manifest carries the same modules, features and statistics as the "
            f"tree, and still differs from what the generator produces. First difference at {where}. "
            f"The manifest records every model, column, route and schema, so a rename or a changed "
            f"docstring moves it without moving any count"
        )

    return failures


def main() -> int:
    """Compare the committed manifest with the tree and print the populations beside the verdict."""
    if interpreter_too_old():
        running = ".".join(str(part) for part in sys.version_info[:3])
        required = ".".join(str(part) for part in REQUIRED_PYTHON)
        print(f"[FAIL] this guard is running on Python {running} and the backend is written to {required}+.")
        print("       The generator reads the tree with ast, so on an older interpreter it cannot parse")
        print("       PEP 695 generics and quietly returns modules with no models, routes or schemas.")
        print("       It would then report the committed manifest as drifted and name the modules it")
        print(f"       failed to read itself. Run this on Python {required} or newer.")
        return 1

    if not MANIFEST_PATH.exists():
        print(f"[FAIL] {MANIFEST_PATH.relative_to(REPO_ROOT).as_posix()}: not found")
        print(f"       The Architecture Map falls back to an empty state without it. Run `{FIX_COMMAND}`")
        return 1

    if not GENERATOR_PATH.exists():
        print(
            f"[FAIL] {GENERATOR_PATH.relative_to(REPO_ROOT).as_posix()}: not found, so there is nothing to compare against"
        )
        return 1

    # Universal newlines: see the note on line endings in this module's docstring.
    committed_text = MANIFEST_PATH.read_text(encoding="utf-8")

    try:
        regenerated_text, parse_warnings = render_tree()
    except SystemExit as exc:
        # generate_manifest() exits when backend/app/modules is not a directory.
        print(f"[FAIL] the generator refused to run (exit {exc.code}), so this guard has no verdict to give")
        return 1

    committed_modules, committed_features, committed_stats = summarise(json.loads(committed_text))
    tree_modules, tree_features, tree_stats = summarise(json.loads(regenerated_text))

    print(MANIFEST_PATH.relative_to(REPO_ROOT).as_posix())
    print(
        f"  committed    modules = {len(committed_modules):>4}  frontend features = {len(committed_features):>4}  "
        f"bytes = {len(committed_text.encode('utf-8')):>9}"
    )
    print(
        f"  regenerated  modules = {len(tree_modules):>4}  frontend features = {len(tree_features):>4}  "
        f"bytes = {len(regenerated_text.encode('utf-8')):>9}"
    )
    print(f"  statistics compared: {len(set(committed_stats) | set(tree_stats))}")
    print(f"  files the generator could not parse: {len(parse_warnings)}")

    failures = compare(committed_text, regenerated_text)

    # Ahead of the drift messages, because it changes what they mean. A module
    # the generator could not read is in the manifest with its contents missing,
    # so a difference here is not evidence about the committed file.
    if parse_warnings:
        failures.insert(
            0,
            f"[FAIL] the generator could not parse {len(parse_warnings)} file(s), so the manifest it "
            f"produced has modules with no models, routes or schemas and this comparison is not "
            f"evidence about the committed file: {'; '.join(parse_warnings[:5])}",
        )

    if failures:
        print()
        for failure in failures:
            print(failure)
        print()
        print(f"Fix: {FIX_COMMAND}")
        print(
            "Nothing else runs that generator, so the committed manifest is only ever as fresh as the "
            "last person who remembered. That is what this guard replaces."
        )
        return 1

    print()
    print(
        f"[OK] the committed manifest is exactly what the generator produces: {len(tree_modules)} modules, "
        f"{len(tree_features)} frontend features"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
