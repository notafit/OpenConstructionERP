# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Locale-scoped message bundle for the funding module.

The funding findings used to live in the shared validation bundle, which ships
four languages. Every other reader got them in English, on a funding screen
whose labels, buttons and guide were already in their own language, so a
funding officer working in French read French controls around English
sentences. The shared bundle could not simply gain more languages for these
keys: its tests require every locale file it carries to answer every key it
knows, so a French file holding only the funding messages would have failed
them, and translating all of the shared messages is a separate piece of work.

A module-local bundle is the pattern bcf, compliance, compliance_ai,
cost_match, dashboards and rebar_schedule already follow. It carries one file
per offered interface language and constructs the shared
:class:`~app.core.validation.messages.MessageBundle`, so a regional code such
as ``pt-BR`` resolves through its base language the same way everywhere.

Public API
    * :func:`translate(key, locale="en", **params) -> str`
    * :func:`is_key_present(key, locale)` - diagnostic used by tests.
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
    """Resolve a funding message key for ``locale`` with ``str.format`` params."""
    return _bundle.translate(key, locale=locale, **params)


def is_key_present(key: str, locale: str = DEFAULT_LOCALE) -> bool:
    """Return ``True`` if ``key`` exists in ``locale`` without any fallback."""
    return _bundle.is_key_present(key, locale=locale)


def available_locales() -> list[str]:
    """List locales currently loaded into the funding bundle."""
    return _bundle.available_locales()


def reload_bundle() -> None:
    """Force a cache refresh (test helper)."""
    _bundle.reload()


__all__ = ["available_locales", "is_key_present", "reload_bundle", "translate"]
