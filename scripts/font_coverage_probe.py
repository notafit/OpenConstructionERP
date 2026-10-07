"""Report, per locale, the words a webfont stylesheet cannot draw in one typeface.

A word rendered partly by a webfont and partly by the system fallback is drawn
in two typefaces at once. This probe counts those words per locale, under two
different definitions of "covered", because the difference between them is
where the interesting defects live:

  declared  a character counts as covered when its codepoint falls inside some
            @font-face unicode-range. This is what the browser uses to decide
            whether to DOWNLOAD a face.
  rendered  a character counts as covered when its codepoint is inside a
            unicode-range AND the font file behind that face actually has a
            glyph for it. This is what the browser PAINTS.

The two disagree exactly when a face claims a range it cannot draw. Such a face
costs a font fetch that renders nothing, and the declared column is what makes
that visible. Run with --fonts to get both columns; without it, only declared.

Needs fonttools and brotli, so it is a script you run rather than a CI gate:

    python scripts/font_coverage_probe.py \
        --css frontend/public/assets/vendor/fonts/fonts.css \
        --fonts frontend/public/assets/vendor/fonts/webfonts \
        --locales frontend/src/app/locales
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

from fontTools.ttLib import TTFont

FACE_RE = re.compile(r"@font-face\s*\{(.*?)\}", re.S)
FAMILY_RE = re.compile(r"font-family:\s*['\"]?([^;'\"]+)['\"]?\s*;")
RANGE_RE = re.compile(r"unicode-range:\s*([^;]+);")
URL_RE = re.compile(r"url\(\s*['\"]?([^)'\"]+)['\"]?\s*\)")

# Locale files are `"key": "value",` maps. Only the values carry translated
# prose; the keys are ASCII identifiers and would dilute every count.
VALUE_RE = re.compile(r':\s*"((?:[^"\\]|\\.)*)"')

CYRILLIC_BLOCKS = (
    (0x0400, 0x04FF),
    (0x0500, 0x052F),
    (0x2DE0, 0x2DFF),
    (0xA640, 0xA69F),
)


def parse_ranges(text: str) -> list[tuple[int, int]]:
    """Turn a CSS unicode-range value into inclusive codepoint pairs."""
    out: list[tuple[int, int]] = []
    for raw in text.split(","):
        part = raw.strip()
        if not part.startswith("U+"):
            continue
        body = part[2:]
        if "-" in body:
            low, high = body.split("-", 1)
            out.append((int(low, 16), int(high, 16)))
        elif "?" in body:
            out.append((int(body.replace("?", "0"), 16), int(body.replace("?", "F"), 16)))
        else:
            point = int(body, 16)
            out.append((point, point))
    return out


def load_faces(css_path: Path, font_root: Path | None) -> list[dict]:
    """Read every @font-face out of a stylesheet, optionally with its real cmap."""
    faces: list[dict] = []
    for body in FACE_RE.findall(css_path.read_text(encoding="utf-8")):
        family = FAMILY_RE.search(body)
        url = URL_RE.search(body)
        if not family or not url:
            continue
        declared = RANGE_RE.search(body)
        faces.append(
            {
                "family": family.group(1).strip(),
                "ranges": parse_ranges(declared.group(1)) if declared else [(0x0, 0x10FFFF)],
                "url": url.group(1).strip(),
                "cmap": None,
            }
        )
    if font_root is None:
        return faces
    for face in faces:
        name = face["url"].split("/")[-1].split("?")[0]
        path = font_root / name
        if not path.exists():
            raise SystemExit(f"font file named by the stylesheet is missing: {path}")
        face["cmap"] = set(TTFont(path).getBestCmap())
    return faces


def covered(point: int, faces: list[dict], mode: str, memo: dict) -> bool:
    key = (point, mode)
    if key in memo:
        return memo[key]
    hit = False
    for face in faces:
        if not any(low <= point <= high for low, high in face["ranges"]):
            continue
        if mode == "declared" or (face["cmap"] is not None and point in face["cmap"]):
            hit = True
            break
    memo[key] = hit
    return hit


def in_script(word: str, blocks: tuple[tuple[int, int], ...]) -> bool:
    return any(any(low <= ord(ch) <= high for low, high in blocks) for ch in word)


def words_of(text: str):
    """Yield maximal runs of letters and marks.

    Digits, punctuation and the {{placeholder}} syntax are separators, so a
    placeholder cannot fuse two words into one.
    """
    word: list[str] = []
    for ch in text:
        if unicodedata.category(ch)[0] in ("L", "M"):
            word.append(ch)
            continue
        if word:
            yield "".join(word)
            word = []
    if word:
        yield "".join(word)


def measure(locale_path: Path, faces: list[dict], mode: str, memo: dict) -> tuple[int, int, list[str]]:
    total = 0
    split = 0
    samples: list[str] = []
    for value in VALUE_RE.findall(locale_path.read_text(encoding="utf-8")):
        try:
            text = json.loads(f'"{value}"')
        except json.JSONDecodeError:
            text = value
        for word in words_of(text):
            if not in_script(word, CYRILLIC_BLOCKS):
                continue
            total += 1
            key = (word, mode)
            verdict = memo.get(key)
            if verdict is None:
                verdict = len({covered(ord(ch), faces, mode, memo) for ch in word}) > 1
                memo[key] = verdict
            if verdict:
                split += 1
                if len(samples) < 3 and word not in samples:
                    samples.append(word)
    return total, split, samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--css",
        required=True,
        type=Path,
        help="stylesheet holding the @font-face rules",
    )
    parser.add_argument(
        "--fonts",
        type=Path,
        default=None,
        help="directory holding the woff2 files the CSS names",
    )
    parser.add_argument("--locales", required=True, type=Path, help="directory of locale .ts files")
    parser.add_argument(
        "--only",
        default="",
        help="comma separated locale codes, default every locale with Cyrillic",
    )
    args = parser.parse_args()

    faces = load_faces(args.css, args.fonts)
    modes = ["declared"] + (["rendered"] if args.fonts else [])
    wanted = [code.strip() for code in args.only.split(",") if code.strip()]

    files = sorted(args.locales.glob("*.ts"))
    if wanted:
        files = [path for path in files if path.stem in wanted]

    memo: dict = {}
    print(f"css={args.css.name}  faces={len(faces)}  modes={', '.join(modes)}")
    header = f"{'locale':<8}{'cyr words':>11}" + "".join(f"{mode + ' split':>17}" for mode in modes)
    print(header)
    print("-" * len(header))
    for path in files:
        total = 0
        cells: list[str] = []
        note = ""
        for mode in modes:
            total, split, samples = measure(path, faces, mode, memo)
            share = (split / total * 100) if total else 0.0
            cells.append(f"{split:>9}{share:>7.1f}%")
            if mode == modes[-1] and samples:
                note = "   eg " + " ".join(samples)
        if total:
            print(f"{path.stem:<8}{total:>11}" + "".join(cells) + note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
