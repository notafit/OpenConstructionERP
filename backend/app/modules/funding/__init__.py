# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Public funding module: grants, subsidies and the paperwork they carry.

A construction project funded from public money runs a second project beside
the building one, with its own deadlines, its own definition of what a cost
is, and its own way of failing. This module is that second project.

The lifecycle it models is the same everywhere public money is granted:

* **Programme** -- what a body offers, on what terms, to whom, until when.
* **Application** -- a project asking one programme for a share of its costs,
  and the award notice that comes back with an amount and with conditions.
* **Disbursement** -- drawing part of an awarded amount against real spending.
* **Proof of use** -- showing afterwards where the money went.
* **Obligation** -- every dated thing the award makes someone responsible for.
* **Cost allocation** -- which of the project's costs the programme will
  actually count, which it will not, and why.

The vocabulary is deliberately country-neutral, because the shape is. German
practice names the same six things Förderprogramm, Zuwendungsantrag with its
Zuwendungsbescheid, Mittelabruf, Verwendungsnachweis, Auflagen and Fristen,
and zuwendungsfähige Kosten. United States federal practice names them notice
of funding opportunity, application with its notice of award, drawdown,
federal financial report, terms and conditions, and allowable costs. The
differences that matter are numbers and document formats, not entities, so
the numbers live on the programme record and arrive with a Country Pack while
the entities stay here.

Three rules decide whether a grant survives its own audit, and all three are
dates or ratios rather than documents, which is why they are validation rules
and not a checklist. Work started before the application was filed is not
fundable. Costs dated outside the award period are not fundable. An applicant
who does not carry the share the programme requires has not met its terms.
See ``validators.py``, where each is stated once with the reason attached.
"""


async def on_startup() -> None:
    """Module startup hook -- register permissions and validation rules."""
    from app.modules.funding.permissions import register_funding_permissions
    from app.modules.funding.validators import register_funding_rules

    register_funding_permissions()
    register_funding_rules()
