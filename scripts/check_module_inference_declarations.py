#!/usr/bin/env python3
"""Report modules that reach an inference primitive without declaring that they do.

The question this exists to answer is the first one a regulator or a buyer asks:
which of the things you ship performs inference, and on what. Today that can only
be answered by a person reading every module and forming an opinion, which is how
a sweep of this platform's AI surface finished without having opened the module
that transcribes speech.

`ModuleManifest.inference` lets a module answer for itself. This gate checks the
answers against the code, because a register nobody checks is a register that
drifts, and it is quoted outside the project.

WHY THIS IS NOT SCOPED BY NAME

A gate keyed on directory names passes `phonelog` in silence. That is not a
hypothetical: `phonelog` is a filing-sounding name on a module that posts call
audio to a hosted speech-to-text endpoint, and a keyword sweep of this tree
missed it for exactly that reason. Names are also wrong in the other direction -
`smart_views` sounds like inference and is a pure rule engine with hard-coded
predicates, and `bimlv` sounds like nothing at all.

So the scope is what a module actually reaches. Every import in `backend/app` is
read with `ast` and resolved into a graph, and a module is in scope when it, or
anything it imports without leaving `app/core`, imports one of the PRIMITIVES
below.

WHY THE WALK STOPS AT ANOTHER MODULE'S BOUNDARY

Following every import edge without limit puts 56 of 193 modules in scope, and
most of that is one module calling another module's public service function that
happens to run a model inside. Measured on 2026-08-28: 31 modules reach a
primitive on their own account, and 25 more only through another module. Those 25
are consuming somebody else's inference, and the producer is the one carrying the
obligation, so lumping them together produces a number nobody can act on. The
walk therefore goes freely through `app/core` and stops at the boundary of
another `app/modules/<other>`.

A module that consumes another's inference is not off the hook, it is a different
answer: `InferenceRole.CONSUMES_RESULT`, which this gate does not require but
does check for completeness when it is given.

WHY A MODULE MAY DECLARE MORE THAN ONCE

One answer per module is the wrong shape for at least one endpoint here. The
catalogue matcher scores with a rapidfuzz ratio and two fixed bonuses in lexical
mode, which is a predefined string rule, and with a learned encoder in semantic
and hybrid mode, and the mode arrives as a request parameter with lexical as the
default. A single role would be wrong for most of that endpoint's calls. So the
manifest may carry a tuple, each entry saying in `when` which calls it covers,
and this gate treats a module as declared when any entry admits inference and as
contradicted only when every entry denies it.

The rules for what makes a declaration too thin exist twice: once on the objects,
in InferenceDeclaration.gaps and ModuleManifest.inference_gaps, and once here in
the ast loop. That is the price of a gate that refuses to import manifests, which
it refuses so that a manifest cannot change the answer by running code. Edit one
and edit the other, because the two drifting apart makes the register wrong
rather than merely noisy.

WHAT A GRAPH ROOTED AT PRIMITIVES CANNOT FIND

A model loaded in place, reaching no shared entry point at all. Two exist today:
`erp_chat/service.py` posts to two provider endpoints with its own HTTP client
rather than through the shared layer, and `costs/matcher.py` constructs a
sentence-transformer itself when the shared embedder is unavailable. Both modules
happen to be in scope for other reasons, so neither is currently hidden by this -
but the shape is, so a second textual pass runs alongside the graph and reports
separately. It is a text instrument, so it reads a hostname in a comment the same
way it reads one in a call, and every member of its list has been opened and read.
Modules that host a primitive are excluded from it: the graph starts at those
files, so naming them as what the graph cannot see is simply untrue.

WHAT THIS GATE DOES NOT SEE AT ALL

`ModuleLoader.discover()` walks the shipped directory plus any runtime root
attached by `module_runtime_root`. This gate walks the shipped directory only, so
a module written by the module builder and installed at runtime is outside its
population entirely. That is exactly the Article 25 case - a user who modifies the
intended purpose becomes the provider - so the omission is worth knowing rather
than worth quietly closing here: the honest place to catch it is the builder,
which now writes a declaration into every module it generates.

Run from anywhere:

    python scripts/check_module_inference_declarations.py

It reports and exits 0 by design, so that the number can be read before anything
starts failing a build on it. `--strict` turns findings into a non-zero exit.
An optional path argument scans a different app directory instead, which is what
the negative-control test uses so it never has to write into the live tree:

    python scripts/check_module_inference_declarations.py /path/to/fixture/app
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys
from collections import defaultdict, deque

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "backend" / "app"

# The inference primitives, as dotted module names. Every entry was opened and
# read before it was put here, because the obvious way to build this list is to
# grep for the names of CV and model libraries, and that method is wrong in a
# way that looks right: it flags the file that DENIES using them.
# `match_elements/symbol_signature.py` says "no YOLO / PaddleOCR", and
# `takeoff/plan_read.py` carries "whisper" in a list of models that are NOT
# vision capable. Three such false roots were removed from an earlier draft of
# this list, and they had inflated the reported population by nine modules.
PRIMITIVES: dict[str, str] = {
    "app.modules.ai.ai_client": "hosted large language and vision models, every provider the platform supports",
    "app.core.match_service.reranker_ai": "hosted model, reranks match candidates",
    "app.core.translation.llm_translator": "hosted model, translates",
    "app.modules.phonelog.transcription": "hosted speech to text, posted straight to the provider",
    "app.core.vector": "a local embedding model",
    "app.core.vector_index": "a local embedding model, through the index",
    "app.core.embedding_pool": "a local embedding model, through the worker pool",
    "app.core.embedding_installer": "fetches and installs the local embedding model",
    "app.modules.file_search.extractors": "a local recognition model, Tesseract",
}

# A model constructed in place. Matched against source text rather than the
# import graph, because these reach no shared entry point for a graph to follow.
IN_PLACE_MODEL = re.compile(
    r"SentenceTransformer\s*\(|pytesseract\.image_to|paddleocr\.\w+\s*\(|PaddleOCR\s*\(|YOLO\s*\(|"
    r"api\.(anthropic|openai|deepseek|groq|mistral|together|fireworks|perplexity|cohere|x)\.(com|ai|xyz)"
)

# Roles that assert this module produces no inference of its own. Declaring one
# of these while reaching a primitive is a contradicted declaration, which is a
# worse finding than saying nothing at all: silence is visibly silence, and a
# wrong entry is the one that gets quoted.
DENYING_ROLES = frozenset({"rule_based", "none"})
KNOWN_ROLES = frozenset({"calls_model", "consumes_result", "rule_based", "none"})


def dotted(path: pathlib.Path, app: pathlib.Path) -> str:
    parts = list(path.relative_to(app.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def owning_module(dot: str) -> str | None:
    """The `app/modules/<name>` a dotted name belongs to, or None for core."""
    parts = dot.split(".")
    return parts[2] if len(parts) >= 3 and parts[:2] == ["app", "modules"] else None


def build_graph(app: pathlib.Path) -> tuple[dict[str, set[str]], list[str]]:
    """Every `app.`-internal import edge in the tree, read with ast.

    Returns the graph and the list of files that could not be parsed. The
    failures are returned rather than swallowed: this tree needs Python 3.12 to
    parse at all - PEP 695 generics appear in `ai_client.py`, which is the main
    primitive - and on 3.11 that file fails to parse while the scan still prints
    a confident number about a graph missing its most important root.
    """
    files = [p for p in app.rglob("*.py") if "__pycache__" not in p.parts]
    known = {dotted(p, app) for p in files}
    edges: dict[str, set[str]] = defaultdict(set)
    failures: list[str] = []

    for path in files:
        dot = dotted(path, app)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            failures.append(f"{dot}: {exc}")
            continue
        pkg = dot if path.name == "__init__.py" else dot.rsplit(".", 1)[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                edges[dot].update(a.name for a in node.names if a.name.startswith("app."))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = pkg.split(".")
                    for _ in range(node.level - 1):
                        base = base[:-1]
                    target = ".".join([*base, node.module]) if node.module else ".".join(base)
                else:
                    target = node.module or ""
                if not target.startswith("app."):
                    continue
                edges[dot].add(target)
                # `from app.core import vector` names a symbol that is a module.
                for alias in node.names:
                    candidate = f"{target}.{alias.name}"
                    if candidate in known:
                        edges[dot].add(candidate)

    def normalise(target: str) -> str:
        parts = target.split(".")
        while parts:
            candidate = ".".join(parts)
            if candidate in known:
                return candidate
            parts.pop()
        return target

    graph: dict[str, set[str]] = defaultdict(set)
    for src, targets in edges.items():
        graph[src].update(normalise(t) for t in targets)
    graph["__known__"] = known
    return graph, failures


def primitives_reached(module: str, graph: dict[str, set[str]]) -> set[str]:
    """Primitives this module reaches without stepping into another module."""
    start = [d for d in graph["__known__"] if owning_module(d) == module]
    seen, queue, hits = set(start), deque(start), set()
    while queue:
        current = queue.popleft()
        for nxt in graph.get(current, ()):
            if nxt in PRIMITIVES and owning_module(nxt) != module:
                hits.add(nxt)
            if nxt in seen:
                continue
            owner = owning_module(nxt)
            if owner is not None and owner != module:
                continue
            seen.add(nxt)
            queue.append(nxt)
    # A module that holds a primitive of its own is in scope without importing
    # anyone. `file_search` is exactly this, and a reachability measure alone
    # never names it.
    hits.update(p for p in PRIMITIVES if owning_module(p) == module)
    return hits


def _one_declaration(call: ast.Call) -> tuple[str | None, set[str], str | None]:
    """One InferenceDeclaration(...) call, as its role, the fields it filled, and its `when`."""
    role: str | None = None
    filled: set[str] = set()
    condition: str | None = None
    for inner in call.keywords:
        if inner.arg == "role":
            value = inner.value
            if isinstance(value, ast.Attribute):
                role = value.attr.lower()
            elif isinstance(value, ast.Constant) and isinstance(value.value, str):
                role = value.value
        elif inner.arg in {"what", "basis", "when"}:
            # Presence, not content, for `what` and `basis`. Reading those out of
            # the ast would say nothing more: a manifest can fill `basis` with a
            # space, and no gate can tell a real ground from a plausible
            # sentence. Whether the reason holds is a question for a person, and
            # this only makes sure there is one to read.
            #
            # `when` is the exception, and only because one rule is about the
            # value: two declarations claiming the same condition answer one
            # question twice. A `when` that is not a plain literal is left as
            # None, which reads as unknown rather than as equal to anything.
            filled.add(inner.arg)
            if inner.arg == "when" and isinstance(inner.value, ast.Constant) and isinstance(inner.value.value, str):
                # Stripped, because `ModuleManifest.inference_gaps` compares
                # stripped conditions and two rules that differ by a space are
                # two rules.
                condition = inner.value.value.strip()
    return role, filled, condition


def declared_roles(
    manifest: pathlib.Path,
) -> list[tuple[str | None, set[str], str | None]]:
    """Every declaration a manifest carries, as a role, the fields it filled, and its `when`.

    Read with ast rather than by importing, so the gate needs no dependency and
    no database, and so a manifest cannot change the answer by running code.

    A list rather than one answer, because a module whose behaviour changes with
    how it is called declares one entry per case. Collapsing those to a single
    role here would put back exactly the averaging the field exists to avoid: a
    matcher that runs a string rule by default and an encoder on request is
    reported as always doing one of them, and the report is then wrong about
    whichever calls it does not describe.
    """
    try:
        tree = ast.parse(manifest.read_text(encoding="utf-8"), filename=str(manifest))
    except (SyntaxError, UnicodeDecodeError):
        return []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or getattr(node.func, "id", None) != "ModuleManifest":
            continue
        for kw in node.keywords:
            if kw.arg != "inference":
                continue
            if isinstance(kw.value, ast.Call):
                return [_one_declaration(kw.value)]
            if isinstance(kw.value, ast.Tuple | ast.List):
                return [_one_declaration(e) for e in kw.value.elts if isinstance(e, ast.Call)]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_dir", nargs="?", help="app directory to scan (default: backend/app)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero on findings, not only on a broken scan",
    )
    args = parser.parse_args(argv)

    app = pathlib.Path(args.app_dir).resolve() if args.app_dir else APP
    modules_dir = app / "modules"
    if not modules_dir.is_dir():
        print(f"no modules directory under {app}", file=sys.stderr)
        return 1

    graph, failures = build_graph(app)
    if failures:
        print(
            f"{len(failures)} file(s) could not be parsed, so the import graph is partial:",
            file=sys.stderr,
        )
        for failure in failures[:10]:
            print(f"  {failure}", file=sys.stderr)
        print(
            "\nThis tree needs Python 3.12 or newer to parse. A partial graph reports fewer\n"
            "modules in scope and says nothing about why, so this exits rather than printing\n"
            "a number that reads as an answer.",
            file=sys.stderr,
        )
        return 1

    # The root set has to be checked against the tree it claims to describe. If
    # a primitive is renamed and this list is not, every lookup below quietly
    # finds nothing and the gate goes green on a tree it can no longer see.
    missing_roots = [p for p in PRIMITIVES if p not in graph["__known__"]]
    if missing_roots:
        print(
            f"{len(missing_roots)} inference primitive(s) named here are not in {app}:",
            file=sys.stderr,
        )
        for root in missing_roots:
            print(f"  {root}", file=sys.stderr)
        print(
            "\nEvery module is measured by whether it reaches one of these. A root that is not\n"
            "in the tree is reached by nobody, so leaving this unfixed turns the gate green by\n"
            "making it blind. Repoint the entry, or drop it and say why in this file.",
            file=sys.stderr,
        )
        return 1

    directories = [d for d in sorted(modules_dir.iterdir()) if d.is_dir() and not d.name.startswith("_")]
    if not directories:
        print(f"no module directories found under {modules_dir}", file=sys.stderr)
        return 1

    undeclared: dict[str, set[str]] = {}
    contradicted: dict[str, tuple[str, set[str]]] = {}
    # Lists, not one string per module. A module may carry several declarations
    # and several of them may be thin, and assigning would report the last one
    # while the heading counted modules and called them declarations.
    incomplete: dict[str, list[str]] = {}
    unknown: dict[str, list[str]] = {}
    in_place: dict[str, set[str]] = {}
    declared_in_scope = 0

    for module_dir in directories:
        name = module_dir.name
        reached = primitives_reached(name, graph)

        # A module that HOSTS a primitive is excluded from the textual pass. The
        # pass exists to name what the graph cannot see, and the graph is rooted
        # at these files, so reporting them under that heading states something
        # false about the very modules the whole walk starts from. Left in, this
        # list read as five when the number it is actually about is two.
        if not any(owning_module(p) == name for p in PRIMITIVES):
            hits = {
                source.name
                for source in module_dir.rglob("*.py")
                if "__pycache__" not in source.parts
                and IN_PLACE_MODEL.search(source.read_text(encoding="utf-8", errors="replace"))
            }
            if hits:
                in_place[name] = hits

        manifest = module_dir / "manifest.py"
        declarations = declared_roles(manifest) if manifest.exists() else []
        roles = [role for role, _, _ in declarations]

        for role, filled, _ in declarations:
            if role is not None and role not in KNOWN_ROLES:
                unknown.setdefault(name, []).append(role)
            elif role == "calls_model" and "what" not in filled:
                incomplete.setdefault(name, []).append(
                    "calls_model with no `what`: it does not say what is inferred, or on what"
                )
            elif role == "consumes_result" and "what" not in filled:
                incomplete.setdefault(name, []).append(
                    "consumes_result with no `what`: it does not say whose inference it consumes"
                )
            elif role == "rule_based" and "basis" not in filled:
                incomplete.setdefault(name, []).append(
                    "rule_based with no `basis`: a claim that this is not an AI system, with no ground given"
                )
            # Only meaningful across siblings: two declarations that do not say
            # which calls they describe are not two facts, they are one
            # contradiction, and a register cannot print either of them.
            if len(declarations) > 1 and "when" not in filled:
                incomplete.setdefault(name, []).append(
                    f"{role} is one of {len(declarations)} declarations here and has no `when`"
                )

        # The other cross-declaration rule, and the one that has to compare
        # values rather than presence: a register asked for the answer under a
        # condition cannot be handed two of them. `ModuleManifest.inference_gaps`
        # states this rule as well, in the same words on purpose, because the two
        # copies of these rules drifting apart is what makes the register wrong
        # rather than merely noisy.
        conditions = [condition for _, _, condition in declarations if condition]
        for condition in sorted({c for c in conditions if conditions.count(c) > 1}):
            incomplete.setdefault(name, []).append(
                f"two declarations both claim `when` {condition!r}, so neither can be reported"
            )

        if not reached:
            continue
        if not declarations:
            undeclared[name] = reached
        elif all(role in DENYING_ROLES for role in roles):
            # Every declaration denies. One that denies beside one that does not
            # is the mode-dependent case, which is correct rather than
            # contradicted: the module reaches a model on the path the other
            # declaration describes.
            contradicted[name] = (", ".join(sorted({r for r in roles if r})), reached)
        else:
            declared_in_scope += 1

    scope = len(undeclared) + len(contradicted) + declared_in_scope
    print(
        f"inference declarations: {len(directories)} modules scanned under {modules_dir}, "
        f"{scope} reach an inference primitive on their own account, "
        f"{declared_in_scope} of those declare it, {len(undeclared)} are undeclared, "
        f"{len(contradicted)} declare the opposite."
    )

    if contradicted:
        print(f"\n{len(contradicted)} module(s) declare no inference of their own and reach a primitive anyway:")
        for name, (role, reached) in sorted(contradicted.items()):
            print(f"  {name}  declares {role}, reaches {', '.join(sorted(reached))}")
        print(
            "\nThis is worse than saying nothing. An absent declaration is visibly absent; a wrong\n"
            "one is the entry that gets quoted. Either the declaration is out of date, or the\n"
            "module gained a model call nobody updated it for."
        )

    if undeclared:
        print(f"\n{len(undeclared)} module(s) reach an inference primitive and declare nothing:")
        for name, reached in sorted(undeclared.items()):
            print(f"  {name}")
            for primitive in sorted(reached):
                print(f"      {primitive}  ({PRIMITIVES[primitive]})")

    thin = sum(len(reasons) for reasons in incomplete.values())
    if incomplete:
        print(f"\n{thin} declaration(s) in {len(incomplete)} module(s) are too thin to quote:")
        for name, reasons in sorted(incomplete.items()):
            for why in reasons:
                print(f"  {name}: {why}")

    bad_roles = sum(len(roles) for roles in unknown.values())
    if unknown:
        print(f"\n{bad_roles} declaration(s) in {len(unknown)} module(s) use a role outside the vocabulary:")
        for name, roles in sorted(unknown.items()):
            for role in roles:
                print(f"  {name}: {role!r} is not one of {', '.join(sorted(KNOWN_ROLES))}")

    if in_place:
        print(
            f"\n{len(in_place)} module(s) construct a model or call a provider in place, which no import graph finds:"
        )
        for name, hits in sorted(in_place.items()):
            reached_too = bool(primitives_reached(name, graph))
            marker = "also reaches a primitive" if reached_too else "REACHES NO PRIMITIVE, visible only here"
            print(f"  {name}: {', '.join(sorted(hits))}  ({marker})")
        print(
            "\nAny module marked as visible only here would be absent from every count above.\n"
            "That is the shape this second pass exists for, and it is why the graph alone is not\n"
            "the whole measurement."
        )

    findings = len(undeclared) + len(contradicted) + thin + bad_roles
    if findings and args.strict:
        return 1
    if findings:
        print(f"\n{findings} finding(s). Reporting only; pass --strict to make them fail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
