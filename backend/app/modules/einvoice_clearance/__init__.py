# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""E-invoice clearance module.

An invoice leaves this product as a PDF, and in a growing list of countries a
PDF is not an invoice. The tax authority has to see the document - before it is
issued in Mexico, Brazil, Italy, Poland, Romania, Saudi Arabia and India, after
it is issued in Spain and Hungary - and in the clearance countries the invoice
does not legally exist until the authority hands back an identifier.

What this module is not
=======================
It is not a second e-invoicing engine. :mod:`app.modules.einvoice` already
builds EN 16931 documents in both syntaxes across ten profiles, and the finance
router already serves them. That is the decentralised model: build the XML, hand
it to the buyer or a network, done.

Clearance is the architectural opposite of decentralised, and the difference is
not a flag on the same code path. There the document is finished when it is
built; here it is finished when a government platform has answered, which means
a state machine, a round trip that can be rejected with a code somebody will be
asked about by name, an identifier that has to be stored and printed, and a
cancellation that has a statutory window. So this module imports the EN 16931
engine as a library and adds only the round trip.

Shape
=====
``regimes.py``  - what each country does to an invoice, as data.
``adapters.py`` - the government-platform boundary, plus one offline reference
                  implementation so the state machine is exercisable end to end.
``models.py``   - the registration, the document and its append-only trail.
``validators.py`` - the six rules that decide whether a document may go.

No network calls live in this package. Every platform is an adapter, because
eight SOAP clients and their dependency trees inside core would end the promise
that core runs on a 3 GB server.
"""


async def on_startup() -> None:
    """Module startup hook (called by the module loader after mount).

    Registers three things, all load-bearing:

    * the module's permissions, without which ``RequirePermission`` denies an
      unregistered key and every endpoint here is admin-only in production
      while every admin-authenticated test still passes;
    * the ``einvoice_clearance`` validation rule set, which gates submission
      and cancellation;
    * the built-in adapters, which is the offline reference implementation and
      nothing else. A real government client registers itself from its own
      package.

    Idempotent - all three registries overwrite by key, so a hot reload
    re-registers cleanly.
    """
    from app.modules.einvoice_clearance.adapters import register_builtin_adapters
    from app.modules.einvoice_clearance.permissions import register_einvoice_clearance_permissions
    from app.modules.einvoice_clearance.validators import register_einvoice_clearance_rules

    register_einvoice_clearance_permissions()
    register_einvoice_clearance_rules()
    register_builtin_adapters()
