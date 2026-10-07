# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Public funding module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_funding_permissions() -> None:
    """Register permissions for the funding module."""
    permission_registry.register_module_permissions(
        "funding",
        {
            "funding.read": Role.VIEWER,
            "funding.create": Role.EDITOR,
            "funding.update": Role.EDITOR,
            "funding.delete": Role.MANAGER,
            # The programme catalogue is reference data shared by every
            # project in the tenant, and most of it arrives from a Country
            # Pack. Editing one entry changes what every application is
            # measured against, so it sits a level above ordinary records.
            "funding.manage_programmes": Role.MANAGER,
            "funding.submit_application": Role.EDITOR,
            # Recording an award is recording a decision somebody else made.
            # It sets the approved amount, the award period and the
            # conditions, which together drive every deadline the module
            # afterwards holds people to.
            "funding.record_award": Role.MANAGER,
            "funding.request_disbursement": Role.EDITOR,
            "funding.confirm_receipt": Role.MANAGER,
            "funding.submit_proof_of_use": Role.EDITOR,
            "funding.close_application": Role.MANAGER,
        },
    )
