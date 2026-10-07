# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Global presence module - shows who is online and where they are.

Ephemeral, in-memory state only. No database tables, no migrations.
Each connected browser tab holds a WebSocket; the hub aggregates
per-user route and status and fans out changes to every peer.
"""
