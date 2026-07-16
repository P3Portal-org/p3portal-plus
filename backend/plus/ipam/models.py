# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-42 Phase 2: internes Plus-IPAM – Datenmodell (eigene Plus-MetaData).

Drei zustandsbehaftete Tabellen, die den best-effort Core-Simple-IPAM (Phase 1,
``ip_pools``) zu einem verlässlichen IPAM aufwerten:

- ``ip_allocations``  – je eine reservierte/zugewiesene IP (Lebenszyklus
  pending→confirmed→orphaned), Unique ``(pool_id, ip)`` = race-sichere Reservierung.
- ``network_grants``  – ein Netz an User/Gruppe freigeben (polymorph, Muster
  PROJ-45/47). Gleicher Identitäts-Schlüssel wie ``ip_pools`` → IPAM-Pool-Sicht erbt.
- ``ipam_config``     – Single-Row (id=1): zwei Toggles (global an/aus + strikte
  Netz-Sicht). Muster PROJ-64 ``approval_workflow_config``.

Phantom-Tabelle ``ip_pools`` (keep_existing=True) löst den Cross-MetaData-FK von
``ip_allocations`` auf, ohne die Core-Tabelle zu besitzen (Muster PROJ-96
nodes/local_users-Phantoms). Die Core-Tabelle ``ip_pools`` liegt in
``backend/db/models.py`` und wird dort via ``create_all`` angelegt.

NULL-Sentinels: wie bei ``ip_pools`` (Phase 1) werden ``node``/``vlan_tag`` in
``network_grants`` als Sentinels ('' / 0) gehalten, damit der Identitäts-Schlüssel
portabel greift; die Service-Schicht führt None.
"""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)

# Eigene MetaData – getrennt vom Core-Schema
plus_metadata = MetaData()

# ── Phantom-Tabelle (FK-Auflösung auf Core-``ip_pools``) ─────────────────────
# keep_existing=True: SQLAlchemy überschreibt nicht, falls schon in dieser MetaData
ip_pools_phantom = Table(
    "ip_pools", plus_metadata,
    Column("id", Integer, primary_key=True),
    keep_existing=True,
)

# ── ip_allocations ────────────────────────────────────────────────────────────
# Eine reservierte/zugewiesene IP. Status-Lebenszyklus:
#   pending    – beim Deploy-Start reserviert (race-sicher via Unique), noch nicht bestätigt
#   confirmed  – Deploy erfolgreich, VMID+Node+Owner verknüpft
#   orphaned   – die zugehörige VM ist außerhalb P3 verschwunden (nicht auto-freigeben)
# source: proxmox (aus Deploy) | manual (Fremd-IP handisch) | stack (Stack-Deploy)
ip_allocations = Table(
    "ip_allocations", plus_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("pool_id", Integer, ForeignKey("ip_pools.id", ondelete="CASCADE"), nullable=False),
    Column("ip", String, nullable=False),
    Column("status", String, nullable=False),          # pending | confirmed | orphaned
    Column("source", String, nullable=False),          # proxmox | manual | stack
    Column("vmid", Integer),                            # zugeordnete VM (nach confirm)
    Column("portal_node_id", Integer),                 # Installation (für Vanished-Match)
    Column("owner_username", String),                  # wer die IP hält
    Column("job_id", String),                          # Playbook-Deploy-Job
    Column("stack_deployment_id", Integer),            # Stack-Deploy (alternativ zu job_id)
    Column("note", String),                            # optionaler Freitext (Fremd-IP)
    Column("created_at", String, nullable=False),
    Column("confirmed_at", String),
    Column("pending_expires_at", String),              # Verfall nie bestätigter Reservierungen
    # race-sichere Reservierung: pro Pool ist jede IP höchstens einmal belegt
    UniqueConstraint("pool_id", "ip", name="uq_ip_allocation_pool_ip"),
)

# ── network_grants ────────────────────────────────────────────────────────────
# Ein Netz (Bridge/VNet) an einen User oder eine Gruppe freigeben. Polymorph:
# grantee_kind ∈ {user, group}, grantee_id = local_users.id | groups.id (kein harter
# FK wegen Polymorphie). Netz-Identität = (kind, network_name, node, vlan_tag) –
# derselbe Schlüssel wie ``ip_pools`` → die IPAM-Pool-Sicht erbt automatisch.
network_grants = Table(
    "network_grants", plus_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", String, nullable=False),            # bridge | vnet
    Column("network_name", String, nullable=False),
    Column("node", String, nullable=False, server_default=""),   # '' = cluster-weit (vnet)
    Column("vlan_tag", Integer, nullable=False, server_default="0"),  # 0 = untagged
    Column("grantee_kind", String, nullable=False),    # user | group
    Column("grantee_id", Integer, nullable=False),
    Column("created_by", String),
    Column("created_at", String, nullable=False),
    UniqueConstraint(
        "kind", "network_name", "node", "vlan_tag", "grantee_kind", "grantee_id",
        name="uq_network_grant",
    ),
)

# ── ipam_config (Single-Row, id=1) ────────────────────────────────────────────
# Zwei Toggles (Muster PROJ-64 approval_workflow_config). Phase 3 ergänzt hier
# active_backend/external_url/external_token_enc – in Phase 2 NICHT angelegt.
ipam_config = Table(
    "ipam_config", plus_metadata,
    Column("id", Integer, primary_key=True, server_default="1"),
    Column("global_enabled", Integer, nullable=False, server_default="0"),
    Column("strict_network_visibility", Integer, nullable=False, server_default="0"),
    Column("updated_by", String),
    Column("updated_at", String),
    CheckConstraint("id = 1", name="ck_ipam_config_single_row"),
)

# ── Indices ──────────────────────────────────────────────────────────────────
# Free-IP-Berechnung / Usage: alle belegten IPs eines Pools.
Index("idx_ipam_alloc_pool", ip_allocations.c.pool_id)
# Vanished-/Delete-Match: (portal_node_id, vmid).
Index("idx_ipam_alloc_vm", ip_allocations.c.portal_node_id, ip_allocations.c.vmid)
# Orphan-Liste + Pending-Sweep.
Index("idx_ipam_alloc_status", ip_allocations.c.status)
# Job-/Stack-Bindung (confirm/release-Lookup).
Index("idx_ipam_alloc_job", ip_allocations.c.job_id)
Index("idx_ipam_alloc_stack", ip_allocations.c.stack_deployment_id)
# Grant-Filter: schneller Lookup pro Netz.
Index("idx_network_grant_net", network_grants.c.kind, network_grants.c.network_name)
