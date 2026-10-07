# Contributing to OpenConstructionERP

Thank you for your interest. OpenConstructionERP is an open-source platform for
construction cost estimation, and the work that comes in from outside genuinely shapes
what gets built. Read the next section before you write any code, because the route in
is not the one most projects use.

## How contributions work here

This project does not accept external pull requests. Not for a module, not for a one
line typo fix, not from anyone outside the core team. Pull requests are not merged, not
checked out and not copied from, and the same goes for patches, forks and dependency
changes proposed from outside. That is a supply chain decision and it applies uniformly,
so it says nothing about the quality of your work.

We say it here, first, because the alternative is that you build something and find out
afterwards.

What is wanted, and what the team acts on, is the part that is harder to write than the
code. An issue with enough detail to act on. A specification of behaviour that is wrong
or missing for your market, naming the standard or regulation it should follow. A
reproduction: what you did, what happened, what should have happened instead. A report
from adapting the platform to a national market, saying what you had to touch and what
was not there. If you can describe the correct behaviour precisely, that is the
contribution, and the team writes the implementation from scratch and credits the person
who specified it.

If you are running the platform on your own fork, that is what the AGPL-3.0 licence is
for and you owe nobody a pull request. Send the findings instead. They travel further
than a diff does.

[DEVELOPING.md](DEVELOPING.md) is the guide to working on the codebase itself, including
how to brief an AI coding assistant on it.

## Quick Start

```bash
# 1. Clone
git clone https://github.com/datadrivenconstruction/OpenConstructionERP.git
cd OpenConstructionERP

# 2. Start dev environment
docker compose up -d   # PostgreSQL + Redis

# 3. Backend
cd backend
pip install -e ".[dev]"
uvicorn app.main:create_app --factory --reload --port 8000

# 4. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

## Code Style

### Python (Backend)
- Formatter: `ruff format` (line-length=120, set in `backend/pyproject.toml`)
- Linter: `ruff check`
- Type hints required for all public functions
- Docstrings: Google style

### TypeScript (Frontend)
- No automatic formatter. Match the style of the file you are editing.
- Linter: ESLint with `@typescript-eslint/recommended`
- Strict mode enabled

### Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add GAEB X86 export support
fix: correct unit rate calculation for assemblies
refactor: extract validation engine into separate module
docs: update API reference for BOQ endpoints
test: add integration tests for cost database import
chore: update dependencies
```

## Before you call a change finished

This applies to work on your own fork as much as to work by the core team, because these
are the checks that catch the mistakes this codebase actually makes. Nothing here needs
our infrastructure; run them where you are.

- [ ] `ruff format --check` then `ruff check`, from inside `backend/`, which is where the
      configuration lives. Run from the repository root instead and ruff finds no config
      and silently applies a different line length.
- [ ] `pytest`, from inside `backend/`
- [ ] `npm run lint`, from inside `frontend/`
- [ ] `npm run build`, from inside `frontend/`. This is the frontend gate, not
      `npm run typecheck`. The first is `tsc -b` followed by a bundle, the second stops
      at `tsc --noEmit`, and the two disagree often enough that reading a green
      `--noEmit` as a green build has broken `main` more than once.
- [ ] `python scripts/check_repo_hygiene.py` and the other `scripts/check_*.py` guards
      for whatever you touched. They are named for what they check.
- [ ] Every user-facing string goes through a translation key, and the key is added to
      every locale file rather than to `en.ts` alone. A key that exists only in English
      falls back silently in all the others, on screen, with every gate green.
- [ ] Conventional commit message, and no secrets or credentials anywhere in the diff.

A remote run that went green somewhere else is not evidence about the tree in front of
you. The check you run before you push is the one that counts.

## Module Development

Each module lives in `backend/app/modules/` as a directory carrying a `manifest.py`.
There were 193 such directories at the last count, which you can recount with
`ls backend/app/modules/*/manifest.py | wc -l`.

Only `manifest.py` and `__init__.py` are required. Everything else is convention, and
the loader picks up each file if it is there and stays quiet if it is not. Write them in
this order, because each layer depends on the one above it:

```
modules/my_module/
├── manifest.py      # Required. Metadata, version, dependencies, category
├── __init__.py      # Required. Package marker, and on_startup() if you need one
├── models.py        # SQLAlchemy models
├── schemas.py       # Pydantic request and response schemas
├── repository.py    # Data access, no business logic
├── service.py       # Business logic, event publishing
├── router.py        # FastAPI routes, mounted at /api/v1/my-module/
├── permissions.py   # Permission definitions
├── events.py        # Subscriptions to other modules' events
└── validators.py    # Validation rules this module contributes
```

How common each one is across those 193 modules, so you can see what a normal module
actually carries: `router.py` 192, `service.py` 175, `schemas.py` 175,
`permissions.py` 153, `models.py` 152, `repository.py` 114, `events.py` 58,
`validators.py` 44. To recount one, run

```bash
for d in backend/app/modules/*/; do
  [ -f "$d/manifest.py" ] && [ -f "$d/service.py" ] && echo "$d"
done | wc -l
```

The `manifest.py` test in there is what makes the count mean "modules". Two packages
live under the same directory without being modules, `measurement` and
`price_breakdown`, so a plain glob counts files rather than modules. It agrees with
the recipe above for `service.py` today only because neither helper carries one.

A module with no persistence of its own has no `models.py` or `repository.py`, and that
is normal rather than incomplete.

`hooks.py` and `pipeline_nodes.py` are also loaded if present, for filter and action
hooks and for contributing node types to the pipeline builder. Neither is in common use:
no module currently ships a `hooks.py`, and one ships a `pipeline_nodes.py`. Reach for
them only when you know you need them.

Two things that are **not** part of a module directory, despite what you might expect:

- **Tests** live in `backend/tests/`, not inside the module. That is where pytest looks:
  `backend/pyproject.toml` sets `testpaths = ["tests"]`. Eight module directories do
  carry a `tests/` folder of their own, and the tests in them are real, but a default
  `pytest` run does not collect them. Put yours under `backend/tests/` so they run.
- **Migrations** live in `backend/alembic/versions/`. The scaffold generates a template
  revision in the module for you to move there once you have set its `down_revision`.

See existing modules (`boq`, `costs`, `projects`) for reference implementations, and
[the module development quickstart](docs/module-development/quickstart.md) for the
file-by-file walkthrough.

## Reporting Issues

- Use [GitHub Issues](https://github.com/datadrivenconstruction/OpenConstructionERP/issues)
- Include: version, steps to reproduce, expected vs actual behavior
- For security issues, see [SECURITY.md](SECURITY.md)

## Licensing

OpenConstructionERP is dual licensed, AGPL-3.0 for the community edition and a
commercial licence for enterprise use. Because code is written by the core team rather
than merged from outside, there is no contributor licence agreement to sign and no bot
that will ask you for one.

Specifications, issue text and reproductions that you send in may be used to build the
corresponding feature, which then ships under both licences like everything else. If
that matters for something you are about to send, say so and we will talk it through
first.

## Questions?

- Open a [Discussion](https://github.com/datadrivenconstruction/OpenConstructionERP/discussions)
- Join our community chat (coming soon)

Thank you for helping make construction cost estimation open and accessible!
