# SPDX-License-Identifier: LicenseRef-P3-Plus
# SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
# === P3 PLUS – PROPRIETARY ===
# Licensed under LICENSE-PLUS (see repo root)
# Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
# Contact: license@p3portal.org

# p3portal.org
"""PROJ-76 Phase 2a: OpenTofu engine plumbing.

This is a *plumbing helper only* — it is **not** wired to any FastAPI route in
Phase 2a (AC-2A-GUARD-1..3). The real `plan`/`apply`/`destroy`/Drift wiring
arrives with the deploy job in Phase 2b. What lives here:

  * the per-node bpg-provider **environment** (token via env, never in HCL/state)
  * the native OpenTofu **state-encryption** passphrase wiring via ``TF_ENCRYPTION``
  * a per-stack **asyncio.Lock** registry ("1 apply per stack")
  * a thin ``run_tofu`` subprocess wrapper (``create_subprocess_exec``, no shell)

State + working directory layout (Tech-Design Phase 2a, Open Points 1/5/6):

    <data_dir>/tofu_state.key          32-byte hex passphrase (entrypoint-gen, chmod 600)
    <data_dir>/stacks/<stack_id>/      working dir = state dir (Volume-persistent)
        main.tf.json                   generated definition (Phase 2b)
        .terraform.lock.hcl            provider lock
        terraform.tfstate              encrypted state
        .terraform/                    ephemeral provider cache (throwaway)

The encryption passphrase is read from ``tofu_state.key`` and injected as an
HCL ``TF_ENCRYPTION`` config at runtime — it is **never** written into a `.tf`
file. The passphrase is deliberately decoupled from ``SECRET_KEY`` (which is
rotatable since PROJ-67): rotating ``SECRET_KEY`` must not break existing states.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

from backend.core.config import settings
from backend.services.nodes_service import NodeRow

logger = logging.getLogger(__name__)

# Filename of the state-encryption passphrase inside the data volume.
STATE_KEY_FILENAME = "tofu_state.key"

# PROJ-66 Phase 2: bpg provider offline-mirror path (single source).
# Mirrors the Dockerfile contract (`mkdir -p /opt/tofu/plugin-mirror` +
# `tofu providers mirror ... /opt/tofu/plugin-mirror` + tofurc filesystem_mirror,
# Dockerfile lines ~98-102). The tooling-health check (run_tofu_check) imports
# this constant + the helper below so the path is never duplicated/hardcoded
# elsewhere. No HCL parsing of tofurc needed — the constant is the contract.
TOFU_PROVIDER_MIRROR = "/opt/tofu/plugin-mirror"


def tofu_provider_mirror_present() -> bool:
    """True when the bpg provider offline-mirror exists and is non-empty.

    Pure filesystem existence/read check (no subprocess, no network), used by
    the PROJ-66 Phase 2 tooling-health check to distinguish ``ready`` (binary +
    mirror) from ``degraded`` (binary, mirror missing → air-gapped deploys fail).
    """
    mirror = Path(TOFU_PROVIDER_MIRROR)
    try:
        return mirror.is_dir() and any(mirror.iterdir())
    except OSError:
        return False

# Per-stack locks: "1 tofu run per stack" (Tech-Design 2a-7, Muster PROJ-74/77).
# Phase 2b wires the HTTP-409 around this lock (deploy_service).
_STACK_LOCKS: dict[str, asyncio.Lock] = {}

# PROJ-87 (designed, dormant — SDN-VNet is a follow-up phase): a single global
# lock that serializes every SDN-touching stack deploy. PVE-SDN commits all
# pending objects with one cluster-wide ``PUT /cluster/sdn`` (affects every
# node), which breaks the per-stack state isolation. The mitigation is to acquire
# this lock *in addition* to (and **before**) the per-stack lock so no two
# SDN-touching deploys run their global apply in parallel (Tech-Design D /
# AC-VN-2 / EC-2). Acquire order SDN→per-stack is deadlock-free (the broader lock
# always comes first). Stays unused in the MVP (validation rejects kind="vnet").
_SDN_APPLY_LOCK = asyncio.Lock()


def get_sdn_apply_lock() -> asyncio.Lock:
    """Return the module-global SDN-apply lock (PROJ-87, dormant in the MVP).

    Single-container reality, like the per-stack locks. The SDN-VNet deploy path
    (follow-up phase, after the bpg-0.78 PVE verification) acquires this lock
    before the per-stack lock to serialize the cluster-wide ``PUT /cluster/sdn``.
    """
    return _SDN_APPLY_LOCK

# Phase 2b: registry of running tofu processes per stack for cancellation (SIGINT).
_RUNNING_TOFU: dict[str, asyncio.subprocess.Process] = {}


# ── Paths ─────────────────────────────────────────────────────────────────────

def _data_dir() -> Path:
    return Path(settings.data_dir)


def state_key_path() -> Path:
    """Absolute path to the state-encryption passphrase file."""
    return _data_dir() / STATE_KEY_FILENAME


def stack_working_dir(stack_id: str, *, create: bool = True) -> Path:
    """Working dir = state dir for a stack: ``<data_dir>/stacks/<stack_id>/``.

    Volume-persistent (AC-2A-STATE-1/3). Never delete while the state still
    tracks resources (Tech-Design Open Point 5).
    """
    path = _data_dir() / "stacks" / str(stack_id)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


# ── State encryption (Open Point 1) ──────────────────────────────────────────

def read_state_passphrase() -> str:
    """Read the state-encryption passphrase from ``tofu_state.key``.

    Raises FileNotFoundError if the key file is missing — it is generated by the
    container entrypoint. Loss of this file makes every encrypted state
    irrecoverable (backup duty documented in the runbook, AC-2A-DOCS).
    """
    path = state_key_path()
    passphrase = path.read_text(encoding="utf-8").strip()
    if not passphrase:
        raise ValueError(f"State-encryption passphrase in {path} is empty")
    return passphrase


def build_encryption_config(passphrase: str) -> str:
    """Build the OpenTofu ``TF_ENCRYPTION`` HCL config for native state encryption.

    Uses the pbkdf2 key-provider + aes_gcm method on both state and plan. The
    passphrase (hex, no special chars) is embedded into the HCL string that is
    passed via the ``TF_ENCRYPTION`` env var — **never** into a `.tf` file
    (AC-2A-STATE-2 / AC-2A-TOKEN-6).
    """
    return (
        'key_provider "pbkdf2" "p3" {\n'
        f'  passphrase = "{passphrase}"\n'
        "}\n"
        'method "aes_gcm" "p3" {\n'
        "  keys = key_provider.pbkdf2.p3\n"
        "}\n"
        "state {\n"
        "  method = method.aes_gcm.p3\n"
        "}\n"
        "plan {\n"
        "  method = method.aes_gcm.p3\n"
        "}\n"
    )


# ── Per-node bpg provider env (Open Point 4) ─────────────────────────────────

def build_node_env(node: NodeRow) -> dict[str, str]:
    """Build the bpg-provider auth env for a node.

    Token is injected via env, never written to HCL/state-plaintext
    (AC-2A-TOKEN-6). ``PROXMOX_VE_INSECURE`` is the inverse of the per-node
    ``verify_ssl`` (feedback_per_node_proxmox_client). ``node.url`` is already
    the base without ``/api2/json`` — bpg appends paths itself.
    """
    if not node.tofu_token_id or not node.tofu_token_secret:
        raise ValueError(
            f"Node '{node.name}' (id={node.id}) has no OpenTofu token configured"
        )
    return {
        "PROXMOX_VE_ENDPOINT": node.url,
        # bpg expects the full token reference: user@realm!name=secret
        "PROXMOX_VE_API_TOKEN": f"{node.tofu_token_id}={node.tofu_token_secret}",
        "PROXMOX_VE_INSECURE": "true" if not node.verify_ssl else "false",
    }


def build_tofu_env(node: NodeRow) -> dict[str, str]:
    """Full subprocess env for a tofu run against ``node``.

    Inherits the process env (PATH, ``TF_CLI_CONFIG_FILE`` from the image, HOME)
    and overlays the bpg auth + ``TF_ENCRYPTION``. ``TF_LOG`` is forced off so
    no token leaks into provider debug logs.
    """
    env = os.environ.copy()
    env.update(build_node_env(node))
    env["TF_ENCRYPTION"] = build_encryption_config(read_state_passphrase())
    env.pop("TF_LOG", None)
    env["TF_IN_AUTOMATION"] = "1"
    return env


# ── Per-stack lock ───────────────────────────────────────────────────────────

def get_stack_lock(stack_id: str) -> asyncio.Lock:
    """Return the asyncio.Lock for a stack, creating it on first use.

    setdefault is atomic enough under the single-threaded asyncio event loop
    (Muster PROJ-74/77 ``_RESTORE_LOCKS``).
    """
    return _STACK_LOCKS.setdefault(str(stack_id), asyncio.Lock())


# ── Subprocess wrapper ───────────────────────────────────────────────────────

async def run_tofu(
    args: list[str],
    stack_id: str,
    node: NodeRow,
    *,
    timeout: float | None = None,
) -> tuple[int, str, str]:
    """Run ``tofu <args>`` for a stack against a node.

    Uses ``asyncio.create_subprocess_exec`` (no ``shell=True``, Security-Regel)
    with ``cwd`` = the stack working dir and the per-node env (token +
    encryption). Returns ``(returncode, stdout, stderr)`` as decoded strings.

    Phase 2a: invoked only by the spike/runbook, **not** by any route
    (AC-2A-GUARD-1..3). Phase 2b wires this into the deploy job + 409 lock.
    """
    workdir = stack_working_dir(stack_id)
    env = build_tofu_env(node)
    proc = await asyncio.create_subprocess_exec(
        "tofu",
        *args,
        cwd=str(workdir),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if timeout is not None:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    else:
        stdout_b, stderr_b = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout_b.decode("utf-8", "replace"),
        stderr_b.decode("utf-8", "replace"),
    )


# ── Phase 2b: streaming run + init + cancel ───────────────────────────────────

def _mask_line(line: str, secret: str | None, extra_secrets: list[str] | None = None) -> str:
    """Mask the bpg token secret (+ optional extra secrets) in a log line.

    Belt-and-suspenders (Open Point 11): ``TF_LOG`` is already forced off (no
    provider debug output) and bpg marks sensitive attributes, but this
    guarantees ``PROXMOX_VE_API_TOKEN`` never leaks into the job log
    (AC-2B-DEP-6). ``extra_secrets`` (PROJ-85 OBS-1, /qa S629) carries the active
    cloud-init passwords so they are masked here too, independent of whether the
    bpg provider redacts them in its plan/apply output.
    """
    if secret and secret in line:
        line = line.replace(secret, "***")
    for extra in extra_secrets or ():
        if extra and extra in line:
            line = line.replace(extra, "***")
    return line


async def run_tofu_streaming(
    args: list[str],
    stack_id: str,
    node: NodeRow,
    *,
    log_path: Path | None = None,
    extra_secrets: list[str] | None = None,
) -> int:
    """Run ``tofu <args>`` and tee stdout/stderr line-by-line into ``log_path``.

    Registers the process in ``_RUNNING_TOFU[stack_id]`` so ``cancel_tofu`` can
    SIGINT it (graceful, tofu writes state + exits). Returns the exit code.
    Used by the Phase-2b deploy/destroy job runner (the bestehende WebSocket
    ``/api/jobs/{job_id}/logs/ws`` tails the same file → no WS change).
    """
    workdir = stack_working_dir(stack_id)
    env = build_tofu_env(node)
    secret = node.tofu_token_secret or None

    proc = await asyncio.create_subprocess_exec(
        "tofu",
        *args,
        cwd=str(workdir),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,  # merge so the live-log is ordered
    )
    _RUNNING_TOFU[str(stack_id)] = proc

    log_fh = log_path.open("a", encoding="utf-8") if log_path else None
    try:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = _mask_line(raw.decode("utf-8", "replace"), secret, extra_secrets)
            if log_fh:
                log_fh.write(line)
                log_fh.flush()
        await proc.wait()
    finally:
        if log_fh:
            log_fh.close()
        _RUNNING_TOFU.pop(str(stack_id), None)
    return proc.returncode or 0


async def tofu_init_if_needed(stack_id: str, node: NodeRow) -> tuple[int, str, str]:
    """Run ``tofu init`` only when the provider cache (``.terraform/``) is absent.

    The ephemeral ``.terraform/`` is throwaway; recreated from the offline
    provider mirror (Phase 2a). Skipped when present to keep plan/apply fast.
    """
    workdir = stack_working_dir(stack_id)
    if (workdir / ".terraform").exists():
        return 0, "", ""
    return await run_tofu(["init", "-input=false", "-no-color"], stack_id, node)


def cancel_tofu(stack_id: str) -> bool:
    """SIGINT a running tofu process for a stack (graceful abort, Open Point 10).

    tofu finishes the in-flight resource, writes state, and exits → no half
    state. Returns True if a process existed. In-memory only (restart-safe:
    a crashed lock/process is simply gone on restart; re-plan shows reality).
    """
    proc = _RUNNING_TOFU.get(str(stack_id))
    if proc is None:
        return False
    try:
        proc.send_signal(signal.SIGINT)
    except ProcessLookupError:  # pragma: no cover – already exited
        return False
    return True
