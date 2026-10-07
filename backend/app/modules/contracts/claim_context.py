# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What other modules add to a payment application's rule context.

The ``pay_application`` rule set checks one progress claim over a plain dict
the contracts service builds (``ContractsService.claim_rule_context``). Some
of what a claim should be checked against lives in other modules, the
subcontractor pay applications rolled into it being the first case. Contracts
must not import those modules: modules are plugins, an install without one is
a normal install, and an import that is only there when the other module is
turns claim submission into a server error on every install without it.

So the dependency points the other way. A module that has something to add
registers a provider here under the context key its rules read, and the
service asks this registry for whatever is registered. With nothing
registered the claim is checked on its own data, which is exactly the
install without that module.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

#: ``provider(session, claim)`` returns the value placed under its key, or
#: ``None`` to leave the key out for this claim. It may be sync or async.
ClaimContextProvider = Callable[[AsyncSession, Any], Any | Awaitable[Any]]

_providers: dict[str, ClaimContextProvider] = {}


def register_claim_context_provider(key: str, provider: ClaimContextProvider) -> None:
    """Add ``provider``'s result to every claim's rule context under ``key``.

    Registering the same key again replaces the provider, so a module that
    registers on every load stays registered once.

    Args:
        key: The context key the provider's rules read, e.g.
            ``"subcontract_rollup"``.
        provider: Called as ``provider(session, claim)`` for each claim that
            is checked; its return value, awaited when it is awaitable,
            becomes ``context[key]``.
    """
    _providers[key] = provider


def unregister_claim_context_provider(key: str) -> None:
    """Remove the provider under ``key``; a key that is not registered is ignored."""
    _providers.pop(key, None)


async def collect_claim_context(session: AsyncSession, claim: Any) -> dict[str, Any]:
    """Ask every registered provider about ``claim``.

    Returns one entry per provider that answered with something other than
    ``None``, and an empty dict when nothing is registered. A provider that
    raises is not swallowed: a rule context that silently lost a section
    would pass the rules that read it.
    """
    collected: dict[str, Any] = {}
    for key, provider in list(_providers.items()):
        value = provider(session, claim)
        if inspect.isawaitable(value):
            value = await value
        if value is not None:
            collected[key] = value
    return collected


__all__ = [
    "ClaimContextProvider",
    "collect_claim_context",
    "register_claim_context_provider",
    "unregister_claim_context_provider",
]
