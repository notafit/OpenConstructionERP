#!/usr/bin/env python3
"""Fail when NOTICE and backend/NOTICE have drifted apart.

Why this exists
---------------
``backend/NOTICE`` is a manual byte copy of the root ``NOTICE``. It exists only
because PEP 639 cannot reach outside the project root, so the wheel can convey
the notice only from a copy that sits beside ``pyproject.toml``.

Nothing stopped an edit landing on one side alone. The enforcement was a single
pytest, ``test_licence_text_ships.py::test_the_two_notice_copies_are_identical``,
which runs in the backend lane after a push. That is too late: the person who
edits the root file has usually finished and moved on by the time it goes red,
and the failure surfaces to whoever pushes next.

It is not hypothetical. Commits 9489d2b96 and 891d56ef0 each edited the root
copy and not the backend one, and the lane went red until 863076d86 restored the
byte copy. This script is the local check that would have caught both before
they were committed.

What it does
------------
Compares the two copies twice, because there are two different ways they drift
and checking only one of them misses the other.

**On disk.** The plain question, are these two files the same right now. This is
what catches the forgot-to-copy case: the root file edited, the backend copy
never touched.

**In the index.** The question that actually decides what lands, because a
commit is built from the index rather than from the working tree. This project
commits with ``git commit --only -- <explicit paths>``, which takes the working
tree state of the paths it is given and leaves every other path at HEAD. So both
files can be byte identical on disk while the commit about to be made carries
only one of them, and a disk-only check waves it through. ``--fix`` makes that
more likely rather than less, by tidying the disk and leaving the staging
untouched, so a gate that only reads the disk would bless the exact state its
own repair created.

Both comparisons normalise CRLF to LF first, the way the gating test does, so a
checkout with Windows line endings is not reported as drift where the test that
actually gates would pass. A gate stricter than the thing it guards is a false
alarm, not extra safety.

The index half is skipped, and says so, when there is no git repository or no
index entry for a path, so a plain run from a tarball still works.

    python scripts/check_notice_mirror.py          # report
    python scripts/check_notice_mirror.py --fix    # copy root over backend

The root file is the source. ``--fix`` copies it over ``backend/NOTICE`` and
never the other way, because the root copy is the one people edit and the
backend copy is the artefact. After a repair, stage both paths.

Exit codes
----------
0  the two copies agree on disk and in the index, or --fix reconciled the disk
1  they have drifted, on disk or in the index (and --fix was not given)
2  one of them is missing
"""

from __future__ import annotations

import argparse
import difflib
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROOT_NOTICE = REPO_ROOT / "NOTICE"
WHEEL_NOTICE = REPO_ROOT / "backend" / "NOTICE"


def _normalise(text: str) -> str:
    """Compare as the gating test compares: CRLF folded to LF."""
    return text.replace("\r\n", "\n")


def _text(path: Path) -> str:
    """Read from the working tree as the gating test reads it."""
    return _normalise(path.read_text(encoding="utf-8"))


def _index_text(path: Path) -> str | None:
    """The staged content of a path, or None when there is no index entry.

    None is not a failure. It means this is not a git checkout, or the path has
    never been added, and in both cases the disk comparison is the only one
    available and the caller says so rather than pretending it checked.
    """
    try:
        rel = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return None
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
            ["git", "show", f":{rel}"],  # noqa: S607
            capture_output=True,
            cwd=REPO_ROOT,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return _normalise(proc.stdout.decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="copy the root NOTICE over backend/NOTICE instead of reporting",
    )
    args = parser.parse_args()

    missing = [p for p in (ROOT_NOTICE, WHEEL_NOTICE) if not p.is_file()]
    if missing:
        for path in missing:
            print(f"[FAIL] missing: {path}", file=sys.stderr)
        return 2

    root, wheel = _text(ROOT_NOTICE), _text(WHEEL_NOTICE)

    if root != wheel and args.fix:
        shutil.copyfile(ROOT_NOTICE, WHEEL_NOTICE)
        print("NOTICE mirror repaired: root NOTICE copied over backend/NOTICE.")
        print("Now stage BOTH paths. Staging only one leaves the same drift in the commit,")
        print("which this check will still catch, because it reads the index as well.")
        root, wheel = _text(ROOT_NOTICE), _text(WHEEL_NOTICE)

    failed = False

    if root != wheel:
        failed = True
        print("[FAIL] NOTICE and backend/NOTICE differ on disk.", file=sys.stderr)
        print(
            "\nbackend/NOTICE is a byte copy of the root NOTICE, carried because PEP 639\n"
            "cannot reach outside the project root. Edit the root file, then copy it over:\n"
            "\n    python scripts/check_notice_mirror.py --fix\n"
            "\nand commit both paths together. A notice edited on one side only leaves the\n"
            "wheel describing a set of bundled binaries that is not the one it holds.\n",
            file=sys.stderr,
        )
        _print_diff(wheel, root, "backend/NOTICE", "NOTICE")

    idx_root, idx_wheel = _index_text(ROOT_NOTICE), _index_text(WHEEL_NOTICE)
    if idx_root is None or idx_wheel is None:
        print("index not checked: no git index entry for one or both copies (disk compared only)")
    elif idx_root != idx_wheel:
        failed = True
        print(
            "[FAIL] NOTICE and backend/NOTICE have drifted in the git index.",
            file=sys.stderr,
        )
        print(
            "\nThe files may agree on disk, but a commit is built from the index, and the\n"
            "staged copies do not match. This is what `git commit --only -- NOTICE` does:\n"
            "it takes the working tree state of the paths you name and leaves every other\n"
            "path at HEAD, so the commit lands one side of the mirror. Stage both:\n"
            "\n    git add -- NOTICE backend/NOTICE\n"
            "\nor name both paths in the commit.\n",
            file=sys.stderr,
        )
        _print_diff(idx_wheel, idx_root, "backend/NOTICE (staged)", "NOTICE (staged)")

    if failed:
        return 1

    checked = "disk and index" if idx_root is not None and idx_wheel is not None else "disk"
    print(f"NOTICE mirror OK: both copies agree on {checked}, {len(root.splitlines())} lines")
    return 0


def _print_diff(before: str, after: str, fromfile: str, tofile: str) -> None:
    diff = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=fromfile,
            tofile=tofile,
            lineterm="",
            n=1,
        )
    )
    shown = diff[:60]
    print("\n".join(shown), file=sys.stderr)
    if len(diff) > len(shown):
        print(f"... {len(diff) - len(shown)} more diff line(s)", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
