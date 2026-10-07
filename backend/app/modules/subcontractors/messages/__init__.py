# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Locale-scoped message bundle for the subcontractors module.

Holds the wording of the subcontract findings this module adds to the
``pay_application`` rule set (``claim_rules.py``). They live here rather than in
the contracts bundle because the contracts module does not know that
subcontractors exist, and rather than in the shared validation bundle because
that one requires every locale file it carries to answer every key it knows. A
module bundle grows one language at a time, which is why funding, bcf,
contracts and the other module bundles exist.

It constructs the shared :class:`~app.core.validation.messages.MessageBundle`,
so a regional code such as ``pt-BR`` resolves through its base language the
same way everywhere, and a key missing from a locale falls back to English
rather than to the raw key.

Public API
    * :func:`translate(key, locale="en", **params) -> str`
    * :func:`is_key_present(key, locale)` - diagnostic used by tests and by the
      rules to tell a known token from one they have to print as it is.
    * :func:`available_locales() -> list[str]`
    * :func:`reload_bundle()` - test helper.
"""

from __future__ import annotations

from pathlib import Path

from app.core.validation.messages import MessageBundle

DEFAULT_LOCALE = "en"
_MESSAGES_DIR = Path(__file__).parent
_bundle = MessageBundle(messages_dir=_MESSAGES_DIR)


def translate(key: str, locale: str = DEFAULT_LOCALE, **params: object) -> str:
    """Resolve a subcontractors message key for ``locale`` with ``str.format`` params."""
    return _bundle.translate(key, locale=locale, **params)


def is_key_present(key: str, locale: str = DEFAULT_LOCALE) -> bool:
    """Return ``True`` if ``key`` exists in ``locale`` without any fallback."""
    return _bundle.is_key_present(key, locale=locale)


def available_locales() -> list[str]:
    """List locales currently loaded into the subcontractors bundle."""
    return _bundle.available_locales()


def reload_bundle() -> None:
    """Force a cache refresh (test helper)."""
    _bundle.reload()


__all__ = ["available_locales", "is_key_present", "reload_bundle", "translate"]
