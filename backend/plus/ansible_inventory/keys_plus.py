# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-83 Plus: Pool-/Global-Keypair-Lifecycle (lazy) + Rotation.

Keys werden lazy beim ersten Bedarf erzeugt (kein Eingriff in create_pool).
Rotation regeneriert das Keypair – bereits ausgebrachte VMs behalten den alten Key
bis zur Neu-Injektion (dokumentierte Grenze, AC-KEYMGMT-4; kein Auto-Re-Key im MVP).
Private Keys werden NIE in Responses/Logs ausgegeben.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text

from backend.db.database import get_db
from backend.services.config_service import decrypt_secret, encrypt_secret


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_ed25519() -> tuple[str, str]:
    """Erzeugt ein Ed25519-Keypair → (private_pem_openssh, public_openssh)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )
    key = Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()).decode()
    public_openssh = key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
    return private_pem, f"{public_openssh.strip()} p3portal-ansible"


# ── Pool-Key ────────────────────────────────────────────────────────────────

async def get_or_create_pool_keypair(pool_id: int) -> tuple[str, str]:
    """Gibt (private_pem, public_openssh) des Pool-Keys zurück; erzeugt ihn lazy."""
    async with get_db() as db:
        row = (await db.execute(
            text("SELECT private_key_enc, public_key FROM ansible_pool_keys WHERE pool_id = :pid"),
            {"pid": pool_id},
        )).mappings().fetchone()
        if row:
            return decrypt_secret(row["private_key_enc"]), row["public_key"]
        priv, pub = _generate_ed25519()
        await db.execute(
            text(
                "INSERT INTO ansible_pool_keys (pool_id, private_key_enc, public_key, created_at) "
                "VALUES (:pid, :pk, :pub, :now)"
            ),
            {"pid": pool_id, "pk": encrypt_secret(priv), "pub": pub, "now": _now()},
        )
        await db.commit()
    return priv, pub


async def get_pool_public_key(pool_id: int) -> str | None:
    priv, pub = await get_or_create_pool_keypair(pool_id)
    return pub


async def get_pool_private_key(pool_id: int) -> str | None:
    priv, pub = await get_or_create_pool_keypair(pool_id)
    return priv


async def rotate_pool_keypair(pool_id: int) -> str:
    """Regeneriert den Pool-Key. Gibt den neuen Public Key zurück."""
    priv, pub = _generate_ed25519()
    async with get_db() as db:
        result = await db.execute(
            text(
                "UPDATE ansible_pool_keys SET private_key_enc = :pk, public_key = :pub, rotated_at = :now "
                "WHERE pool_id = :pid"
            ),
            {"pk": encrypt_secret(priv), "pub": pub, "now": _now(), "pid": pool_id},
        )
        if result.rowcount == 0:
            await db.execute(
                text(
                    "INSERT INTO ansible_pool_keys (pool_id, private_key_enc, public_key, created_at) "
                    "VALUES (:pid, :pk, :pub, :now)"
                ),
                {"pid": pool_id, "pk": encrypt_secret(priv), "pub": pub, "now": _now()},
            )
        await db.commit()
    return pub


# ── Global-Key (Singleton) ──────────────────────────────────────────────────

async def get_or_create_global_keypair() -> tuple[str, str]:
    async with get_db() as db:
        row = (await db.execute(
            text("SELECT private_key_enc, public_key FROM ansible_global_keypair WHERE id = 1")
        )).mappings().fetchone()
        if row:
            return decrypt_secret(row["private_key_enc"]), row["public_key"]
        priv, pub = _generate_ed25519()
        await db.execute(
            text(
                "INSERT INTO ansible_global_keypair (id, private_key_enc, public_key, created_at) "
                "VALUES (1, :pk, :pub, :now)"
            ),
            {"pk": encrypt_secret(priv), "pub": pub, "now": _now()},
        )
        await db.commit()
    return priv, pub


async def get_global_public_key() -> str | None:
    priv, pub = await get_or_create_global_keypair()
    return pub


async def get_global_private_key() -> str | None:
    priv, pub = await get_or_create_global_keypair()
    return priv


async def rotate_global_keypair() -> str:
    priv, pub = _generate_ed25519()
    async with get_db() as db:
        result = await db.execute(
            text(
                "UPDATE ansible_global_keypair SET private_key_enc = :pk, public_key = :pub, rotated_at = :now "
                "WHERE id = 1"
            ),
            {"pk": encrypt_secret(priv), "pub": pub, "now": _now()},
        )
        if result.rowcount == 0:
            await db.execute(
                text(
                    "INSERT INTO ansible_global_keypair (id, private_key_enc, public_key, created_at) "
                    "VALUES (1, :pk, :pub, :now)"
                ),
                {"pk": encrypt_secret(priv), "pub": pub, "now": _now()},
            )
        await db.commit()
    return pub
