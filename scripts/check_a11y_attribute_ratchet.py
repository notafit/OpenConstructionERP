#!/usr/bin/env python3
"""Accessibility ratchet: attributes that never translate, and controls with no name.

Three defect classes live here. They are separate defects with one thing in
common: every gate this repository owns is blind to all three, and for the same
reason each time. Nothing here is a missing key, so the key gates never ask.

  1. AN ATTRIBUTE THAT NEVER WENT THROUGH TRANSLATION.
     aria-label="Close" on a host element is a bare English literal. It renders
     "Close" in all 42 languages, forever. check_i18n_orphan_keys.py cannot see
     it: that gate asks whether a KEY is answered by the locale files, and a
     string that never became a key is never asked about. tsc, eslint and the
     build all pass - the string is valid TypeScript. It was found by walking
     JsxAttribute nodes and asking what each value IS, not by grepping for a
     call form: a grep for `aria-label={t(` is blind to the ones that never
     called t() at all, which is precisely the population.

  2. A VALUE THAT BAKES THE LANGUAGE IN AT MOUNT.
     `useState(t('x'))` runs its initialiser on the first render and never
     again, so the value keeps whatever language the component mounted in. A
     reader who switches language gets a screen whose visible text translated
     and whose attribute did not - confident, fluent, and wrong, which is worse
     for a screen reader user than a missing name. `react-hooks/exhaustive-deps`
     does not catch it because that plugin is not installed in this repository;
     eslint.config.js stubs it with a no-op create() and sets the rule to off,
     so nothing here has ever applied pressure to a dependency array.

  3. AN ICON-ONLY CONTROL WITH NO ACCESSIBLE NAME AT ALL.
     A <button> whose only child is an icon, carrying no aria-label, no
     aria-labelledby, no title and no text, is announced as "button". This is
     not a translation gap - there is nothing to translate. It is a control
     that does not exist for anyone using a screen reader, in every language
     including English.

WHY A RATCHET AND NOT A BAN. All three classes have existing debt that is
deliberately not being fixed in one go - placeholders whose split between real
prose and sample values is a per-string judgement, and hook shapes that feed
toasts rather than attributes. A gate that failed on all of it would be turned
off within a day. So this records today's debt and refuses to let it grow.

HOW THE DETECTORS ARE BUILT, and this is the part that matters if you change
them. Each detector asks a question about ONE item in isolation - is THIS
attribute value human prose on a host element, is THIS hook call seeded from
t(), does THIS control have any accessible name - and the count falls out of
the answers. None of them carries a list of known-bad sites. A detector built
on "these are the 45 known attributes" reports green the moment a component
introduces a 46th, because the new one is not in the set it was told to watch.
The set belongs in the baseline, never in the detector.

WHY THE BASELINE IS KEYED BY TEXT AND NOT BY LINE NUMBER. Line numbers move
under you. While this gate was being written, an unrelated change to
file-manager shifted three tracked sites from lines 273, 291 and 302 to 313,
330 and 341 without altering a character of them. A line-keyed baseline would
have reported three repairs and three new defects in the same run.

USAGE
    python scripts/check_a11y_attribute_ratchet.py
    python scripts/check_a11y_attribute_ratchet.py --update-baseline
    python scripts/check_a11y_attribute_ratchet.py --list          # show current findings

Exit 0 means every finding is either recorded debt or intentionally allowed.
Exit 1 means something new appeared, or a baseline entry names something that
no longer exists (a stale entry - fix it by regenerating, so the baseline keeps
telling the truth about what is left).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO_ROOT, "frontend", "src")
BASELINE_PATH = os.path.join(REPO_ROOT, "scripts", "a11y_attribute_baseline.json")

# Attributes whose value is spoken or shown to a human rather than consumed by code.
TEXT_ATTRS = ("aria-label", "title", "alt", "placeholder")

# Only lowercase JSX tags are real HTML elements. `<Foo title="...">` is a prop
# on a component, which may or may not become an attribute, and is a different
# question with a different answer.
HOST_TAG = re.compile(r"<([a-z][a-z0-9-]*)\b")

ATTR_LITERAL = re.compile(r"\b(" + "|".join(re.escape(a) for a in TEXT_ATTRS) + r')\s*=\s*"([^"\n]*)"')

SEEDED_HOOK = re.compile(r"\buse(State|Ref)\s*(?:<[^>()]*>)?\s*\(")

SKIP_DIR_PARTS = (
    "__tests__",
    "node_modules",
    "dist",
    os.path.join("src", "test"),
    os.path.join("src", "tests"),
)


def is_product_file(path: str) -> bool:
    rel = os.path.relpath(path, SRC)
    if not (rel.endswith(".tsx") or rel.endswith(".ts")):
        return False
    low = rel.lower()
    if ".test." in low or ".spec." in low:
        return False
    norm = rel.replace("\\", "/")
    # The locale files are data, not components: flat objects of translated
    # strings. They cannot hold a JSX attribute or a React hook, so scanning
    # them can only produce a false positive - a translated VALUE that happens
    # to contain angle brackets would read as markup. They are also the most
    # contended files in this tree, rewritten by translation passes constantly,
    # and a gate whose result moves when someone translates a sentence is a gate
    # people learn to ignore. Excluding them changed nothing on the day it was
    # added (0 findings came from them) and keeps it that way on purpose.
    if norm.startswith("app/locales/"):
        return False
    parts = norm.split("/")
    return "__tests__" not in parts and "tests" not in parts and "test" not in parts


def walk_files():
    for root, dirs, names in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "dist")]
        for n in sorted(names):
            p = os.path.join(root, n)
            if is_product_file(p):
                yield p


def rel_of(path: str) -> str:
    return os.path.relpath(path, SRC).replace("\\", "/")


# --------------------------------------------------------------------------
# Is this string human prose, or is it a specimen of the value the field takes?
#
# The distinction is the one a reader who cannot read English would draw: if
# the string TELLS them what to do, they lose something when it stays English.
# If it SHOWS them the shape of the data, translating it teaches a format the
# field will reject. "Clear signature" is prose. "BP-001", "name@company.com"
# and "^F[0-9]{2,3}$" are specimens, and an email address looks the same in
# every language on earth.
# --------------------------------------------------------------------------
_CODEY = re.compile(
    r"""^(
          [A-Z0-9][A-Z0-9._/\-]*            # BP-001, DE-BE, TYPE-A, RFI-142
        | [^@\s]+@[^@\s]+\.[a-z]{2,}        # an email specimen
        | [\^$\\[\](){}|*+?].*              # a regex
        | [#][A-Za-z]{3,}                   # #RRGGBB
        | https?://\S+
        | [-+]?[0-9][0-9.,:%\s/-]*          # bare numbers and ranges
        )$""",
    re.X,
)
# Units and symbol-only strings carry no language.
_NO_LETTERS = re.compile(r"^[^A-Za-z]*$")


def is_human_prose(value: str) -> bool:
    v = value.strip()
    if not v or len(v) < 3:
        return False
    if _NO_LETTERS.match(v):
        return False
    if _CODEY.match(v):
        return False
    # A single lowercase token with no space is usually an identifier or a unit
    # ("m2", "lm", "px"); prose of one word is normally capitalised ("Close").
    if " " not in v and not v[0].isupper():
        return False
    # Must contain at least two consecutive letters somewhere.
    return bool(re.search(r"[A-Za-z]{2}", v))


def end_of_opening_tag(text: str, start: int) -> int:
    """Index of the '>' that closes the opening tag beginning at `start`.

    Scanning BACKWARDS from an attribute to the nearest '<' does not work, and
    the reason is worth keeping: an arrow function in an earlier attribute
    (`onChange={(e) => ...}`) puts a '>' between the tag name and the attribute,
    so a backwards scan walks straight past the tag it was looking for. The
    first version of this file did exactly that and found 1 of 257 literal
    placeholders - a number that looked like a clean tree and was a broken
    reader. Quotes, template literals and brace depth all have to be respected.
    """
    i, n, depth = start, len(text), 0
    while i < n:
        c = text[i]
        if c in "\"'`" or (c == "/" and i + 1 < n and text[i + 1] in "/*"):
            i = _skip_noncode(text, i, n)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == ">" and depth == 0:
            return i
        i += 1
    return -1


JSX_TAG_OPEN = re.compile(r"<([A-Za-z][A-Za-z0-9_.-]*)")


def iter_jsx_tags(text: str):
    """Yield (tag_name, opening_tag_source) for every JSX opening tag."""
    for m in JSX_TAG_OPEN.finditer(text):
        end = end_of_opening_tag(text, m.end())
        if end == -1:
            continue
        yield m.group(1), text[m.start() : end + 1]


def find_untranslated_attributes(path: str, text: str):
    out = []
    for tag, source in iter_jsx_tags(text):
        # Only lowercase tags are real HTML elements; `<Input placeholder="...">`
        # is a component prop, which may never reach the DOM at all.
        if not tag[0].islower():
            continue
        for m in ATTR_LITERAL.finditer(source):
            value = m.group(2)
            if not is_human_prose(value):
                continue
            out.append({"file": rel_of(path), "attr": m.group(1), "text": value})
    return out


def _skip_noncode(text: str, i: int, n: int) -> int:
    """Advance past a string, template literal or comment starting at `i`.

    Comments have to be skipped, and the reason is a defect this file shipped
    with for one draft: an apostrophe in an ordinary code comment ("the locale's
    trade unit") was read as the start of a string literal, so the scanner ran
    past the closing parenthesis and the hook it was standing in was never
    reported. The detector went quiet on a real defect while still reporting its
    neighbour four lines up, which is the worst possible failure - a number that
    moves, so it looks alive.
    """
    c = text[i]
    if c in "\"'`":
        q, i = c, i + 1
        while i < n and text[i] != q:
            i += 2 if text[i] == "\\" else 1
        return i + 1
    if c == "/" and i + 1 < n:
        if text[i + 1] == "/":
            nl = text.find("\n", i)
            return n if nl == -1 else nl
        if text[i + 1] == "*":
            end = text.find("*/", i + 2)
            return n if end == -1 else end + 2
    return i + 1


def _matching_paren(text: str, open_idx: int) -> int:
    depth, i, n = 0, open_idx, len(text)
    while i < n:
        c = text[i]
        if c in "\"'`" or (c == "/" and i + 1 < n and text[i + 1] in "/*"):
            i = _skip_noncode(text, i, n)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


_T_CALL = re.compile(r"(?<![A-Za-z0-9_.])t\s*\(")


def find_seeded_hooks(path: str, text: str):
    out = []
    for m in SEEDED_HOOK.finditer(text):
        open_idx = m.end() - 1
        close = _matching_paren(text, open_idx)
        if close == -1:
            continue
        arg = text[open_idx + 1 : close]
        if not _T_CALL.search(arg):
            continue
        # Name the variable so the baseline entry survives the line moving.
        head = text.rfind("\n", 0, m.start())
        decl = text[head + 1 : m.start()]
        name = ""
        dm = re.search(r"(?:const|let|var)\s*(\[[^\]]*\]|\{[^}]*\}|[A-Za-z0-9_$]+)\s*=\s*$", decl)
        if dm:
            name = re.sub(r"\s+", " ", dm.group(1)).strip()
        out.append({"file": rel_of(path), "hook": "use" + m.group(1), "binding": name})
    return out


_ICON_TAG = re.compile(r"<([A-Z][A-Za-z0-9_]*)\b")
_NAMING_ATTR = re.compile(r"\b(aria-label|aria-labelledby|title)\s*=")


def find_unnamed_icon_controls(path: str, text: str):
    """<button>/<a> whose content is icons only and which carries no name."""
    out = []
    for m in re.finditer(r"<(button|a)\b", text):
        tag = m.group(1)
        # end of the opening tag
        i, n, depth = m.end(), len(text), 0
        while i < n:
            c = text[i]
            if c in "\"'`":
                q, i = c, i + 1
                while i < n and text[i] != q:
                    i += 2 if text[i] == "\\" else 1
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            elif c == ">" and depth == 0:
                break
            i += 1
        if i >= n:
            continue
        open_tag = text[m.start() : i]
        if text[i - 1] == "/":
            continue  # self-closing, no children to inspect
        if _NAMING_ATTR.search(open_tag):
            continue
        close = text.find("</" + tag + ">", i)
        if close == -1:
            continue
        body = text[i + 1 : close]
        if body.count("<" + tag) > 0:
            continue  # nested same-tag; too ambiguous to judge, skip rather than guess

        # Separate the control's CHILDREN from the markup around them. Stripping
        # tags with a regex does not work here: an attribute can contain '>' in
        # an arrow function, and `<CountryFlag code={x} />` contains braces that
        # are attributes, not children. So walk the body, skipping whole tags.
        children, j, n2 = [], 0, len(body)
        while j < n2:
            if body[j] == "<":
                end_tag = end_of_opening_tag(body, j + 1)
                if end_tag == -1:
                    break
                j = end_tag + 1
                continue
            children.append(body[j])
            j += 1
        child_text = "".join(children)

        # An expression child may render anything, including the control's name
        # (`<span>{lang.name}</span>`, `{item.desc}`). We cannot tell statically,
        # so we do not claim it is unnamed. A ratchet that fires on a control
        # that IS named gets switched off, and then it protects nothing - so on
        # this axis it stays deliberately conservative and under-reports.
        if re.search(r"\{[^}]*\}", child_text, re.S):
            continue
        if re.search(r"[A-Za-z]{2}", child_text):
            continue  # a literal text child names it

        icons = sorted(set(_ICON_TAG.findall(body)))
        if not icons:
            continue
        out.append({"file": rel_of(path), "tag": tag, "icons": ",".join(icons)})
    return out


def fingerprint(check: str, item: dict) -> str:
    if check == "untranslated_attributes":
        return "{file}::{attr}::{text}".format(**item)
    if check == "language_frozen_values":
        return "{file}::{hook}::{binding}".format(**item)
    return "{file}::{tag}::{icons}".format(**item)


CHECKS = (
    ("untranslated_attributes", find_untranslated_attributes),
    ("language_frozen_values", find_seeded_hooks),
    ("unnamed_icon_controls", find_unnamed_icon_controls),
)


def scan():
    found = {name: {} for name, _ in CHECKS}
    for path in walk_files():
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        for name, fn in CHECKS:
            for item in fn(path, text):
                fp = fingerprint(name, item)
                found[name][fp] = found[name].get(fp, 0) + 1
    return found


def load_baseline():
    if not os.path.exists(BASELINE_PATH):
        return {"_comment": "", "allowlist": {}, "debt": {}}
    with open(BASELINE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


SHRINK_RULE = (
    "This baseline records accessibility debt that already existed. It MAY ONLY\n"
    "SHRINK. Adding an entry to make this gate pass is not an accepted fix - it\n"
    "converts a defect a reader would hit into a line nobody reads. Fix the site,\n"
    "or, if the string is untranslatable on purpose (a product name, a sample\n"
    "value, a regex), move it to the allowlist with a reason instead."
)


# --------------------------------------------------------------------------
# Negative control.
#
# A gate with no red arm is a gate nobody has tested, and its failure mode is
# that it passes forever. Each case below is a PAIR: a source that differs from
# its clean twin in exactly ONE thing - the thing that check exists to find.
# That matters more than it sounds. An earlier draft of this file "proved" the
# attribute check by deleting the whole element, which every arm would notice
# and which therefore proved nothing about this one.
#
# The must_not_fire cases guard the other direction. A ratchet that reports a
# control which IS named gets switched off within a day, and then it protects
# nothing at all.
# --------------------------------------------------------------------------
SELFTEST = [
    (
        "untranslated_attributes",
        # differs ONLY in literal-vs-t()
        '<button aria-label="Close the dialog"></button>',
        "<button aria-label={t('a.b', { defaultValue: 'Close the dialog' })}></button>",
    ),
    (
        "language_frozen_values",
        # differs ONLY in whether the initialiser calls t()
        "const [title, setTitle] = useState(t('a.b', { defaultValue: 'AI assistant' }));",
        "const [title, setTitle] = useState<string | null>(null);",
    ),
    (
        "unnamed_icon_controls",
        # differs ONLY in the presence of an accessible name
        "<button onClick={go}><X size={16} /></button>",
        "<button onClick={go} aria-label={t('a.b')}><X size={16} /></button>",
    ),
    (
        # Regression: an apostrophe in a COMMENT inside the argument once made
        # the paren scanner run away, so this hook was silently not reported
        # while an identical one four lines above still was. Real shape, taken
        # from features/takeoff/components/CreateRfiFromMeasurementDialog.tsx.
        "language_frozen_values",
        "const [q, setQ] = useState(() =>\n"
        "  t('a.b', {\n"
        "    defaultValue: 'Confirm the measured {{type}} ({{annotation}}) on page {{page}}.',\n"
        "    // Counts prefill as whole pieces with the locale's trade unit code\n"
        "    type: m.type,\n"
        "  }),\n"
        ");",
        "const [q, setQ] = useState<string | null>(\n"
        "  // the locale's trade unit code is resolved during render instead\n"
        "  null,\n"
        ");",
    ),
]

MUST_NOT_FIRE = [
    (
        "untranslated_attributes",
        '<Input placeholder="Search projects" />',
        "a component prop is not an HTML attribute",
    ),
    (
        "untranslated_attributes",
        '<input placeholder="BP-001" />',
        "a specimen value is not prose",
    ),
    (
        "untranslated_attributes",
        '<input placeholder="name@company.com" />',
        "an email specimen looks the same in every language",
    ),
    (
        "unnamed_icon_controls",
        "<button onClick={go}><X size={16} /><span>{label}</span></button>",
        "an expression child may render the name",
    ),
    (
        "unnamed_icon_controls",
        "<button onClick={go}><X size={16} /> Close</button>",
        "a literal text child names it",
    ),
]

FNS = dict(CHECKS)


def selftest() -> int:
    failures = []
    for check, defective, clean in SELFTEST:
        fn = FNS[check]
        if not fn("selftest.tsx", defective):
            failures.append(f"{check} did NOT fire on its planted defect: {defective}")
        if fn("selftest.tsx", clean):
            failures.append(f"{check} fired on the REPAIRED twin: {clean}")
        # every other check must ignore this defect, or the arms are not distinct
        for other, other_fn in CHECKS:
            if other != check and other_fn("selftest.tsx", defective):
                failures.append(f"{other} also fired on {check}'s defect - the arms are not independent")

    for check, source, why in MUST_NOT_FIRE:
        if FNS[check]("selftest.tsx", source):
            failures.append(f"{check} FALSE POSITIVE ({why}): {source}")

    if failures:
        print(f"NEGATIVE CONTROL FAILED ({len(failures)})\n")
        for f in failures:
            print("  " + f)
        print(
            "\nA detector that cannot fire on a planted defect will report a clean tree\n"
            "forever, and the tree will look like it got better. Fix the detector."
        )
        return 1
    print(
        f"negative control OK: {len(SELFTEST)} checks each fire on their own planted defect, stay silent on the\n"
        f"repaired twin, ignore the other checks' defects, and do not fire on {len(MUST_NOT_FIRE)} legitimate shapes."
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="run the negative control")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    found = scan()
    baseline = load_baseline()
    allow = baseline.get("allowlist", {})
    debt = baseline.get("debt", {})

    if args.list:
        for name, items in found.items():
            print(f"{name}: {len(items)}")
            for fp in sorted(items):
                print("   ", fp)
        return 0

    if args.update_baseline:
        new_debt = {}
        for name, items in found.items():
            new_debt[name] = sorted(fp for fp in items if fp not in allow.get(name, {}))
        baseline["debt"] = new_debt
        baseline["allowlist"] = allow
        baseline["_comment"] = SHRINK_RULE.replace("\n", " ")
        with open(BASELINE_PATH, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(baseline, fh, indent=1, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
        total = sum(len(v) for v in new_debt.values())
        print(f"baseline rewritten: {total} recorded findings across {len(new_debt)} checks")
        return 0

    failures, repaired = [], []
    for name, items in found.items():
        known = set(debt.get(name, [])) | set(allow.get(name, {}))
        for fp in sorted(items):
            if fp not in known:
                failures.append((name, fp))
        for fp in sorted(debt.get(name, [])):
            if fp not in items:
                repaired.append((name, fp))

    if failures:
        print(f"NEW ACCESSIBILITY DEFECTS ({len(failures)})\n")
        by = {}
        for name, fp in failures:
            by.setdefault(name, []).append(fp)
        blurb = {
            "untranslated_attributes": "An attribute holding a bare English string. It renders English in every\n"
            "  language and no key gate can see it, because it never became a key.\n"
            "  Fix: t('some.key', { defaultValue: '...' }) plus the key in en.ts and\n"
            "  every locale the check_i18n_orphan_keys.py `missing:` line names.",
            "language_frozen_values": "A value seeded from t() into useState/useRef. The initialiser runs once,\n"
            "  so this freezes the language the component mounted in. Fix: hold the\n"
            "  unset case (null) and derive during render with t in the dependency list.",
            "unnamed_icon_controls": "An icon-only control with no accessible name in ANY language. A screen\n"
            "  reader announces it as 'button'. Fix: give it aria-label={t(...)}.",
        }
        for name, fps in by.items():
            print(f"{name} ({len(fps)})")
            print("  " + blurb[name])
            for fp in fps:
                print("    " + fp)
            print()
        print(SHRINK_RULE)
        print("\nRegenerate deliberately with: python scripts/check_a11y_attribute_ratchet.py --update-baseline")
        return 1

    if repaired:
        print(f"STALE BASELINE ENTRIES ({len(repaired)}): recorded debt that no longer exists.\n")
        for name, fp in repaired:
            print(f"  {name}  {fp}")
        print(
            "\nThis is good news that has to be written down: the baseline must keep\n"
            "telling the truth about what is left, or the next reader trusts a number\n"
            "that is no longer real. Regenerate it:\n"
            "  python scripts/check_a11y_attribute_ratchet.py --update-baseline"
        )
        return 1

    total = sum(len(v) for v in found.values())
    recorded = sum(len(v) for v in debt.values())
    print(
        f"a11y attribute ratchet OK: {total} findings, all recorded ({recorded} as debt, the rest allowlisted). "
        "No new untranslated attributes, language-frozen values or unnamed icon controls."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
