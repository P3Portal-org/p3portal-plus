// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: API-Helper für Stacks (deklaratives Infrastructure-Modell).
import client from '../../api/client'

const BASE = '/api/stacks'

// ── List + Create ──────────────────────────────────────────────────────────

export async function fetchStacks({ q, includeDeleted } = {}) {
  const params = {}
  if (q) params.q = q
  if (includeDeleted) params.include_deleted = true
  const { data } = await client.get(BASE, { params })
  return data
}

export async function createStack(payload) {
  // payload: { yaml_text } ODER { name, description, version, resources, source_kind }
  const { data } = await client.post(BASE, payload)
  return data
}

// ── Detail / Update / Delete ────────────────────────────────────────────────

export async function fetchStack(id) {
  const { data } = await client.get(`${BASE}/${id}`)
  return data
}

/**
 * PUT mit ETag-Concurrency (AC-CONC). Wirft den axios-Fehler weiter, damit
 * der Aufrufer 409 (EtagConflictResponse) und 202 (pending_approval) unterscheiden kann.
 * @returns {{ kind: 'ok'|'pending', data }} – kind='pending' bei HTTP 202.
 */
export async function updateStack(id, payload, changeSummary) {
  const params = {}
  if (changeSummary) params.change_summary = changeSummary
  const resp = await client.put(`${BASE}/${id}`, payload, { params })
  if (resp.status === 202) return { kind: 'pending', data: resp.data }
  return { kind: 'ok', data: resp.data }
}

/** @returns {{ kind: 'ok'|'pending', data }} – kind='pending' bei HTTP 202. */
export async function deleteStack(id) {
  const resp = await client.delete(`${BASE}/${id}`)
  if (resp.status === 202) return { kind: 'pending', data: resp.data }
  return { kind: 'ok', data: null }
}

// ── Validate / Preview ────────────────────────────────────────────────────────

export async function validateStack(payload) {
  const { data } = await client.post(`${BASE}/validate`, payload)
  return data
}

export async function previewNewStack(payload) {
  const { data } = await client.post(`${BASE}/preview`, payload)
  return data
}

export async function previewSavedStack(id) {
  const { data } = await client.post(`${BASE}/${id}/preview`)
  return data
}

// ── Versionen ──────────────────────────────────────────────────────────────────

export async function fetchVersions(id) {
  const { data } = await client.get(`${BASE}/${id}/versions`)
  return data
}

export async function fetchVersion(id, versionNumber) {
  const { data } = await client.get(`${BASE}/${id}/versions/${versionNumber}`)
  return data
}

// ── Diff (A-vs-aktuell oder A-vs-B) ──────────────────────────────────────────

export async function fetchDiff(id, from, to) {
  const { data } = await client.get(`${BASE}/${id}/diff`, { params: { from, to } })
  return data
}

// ── Restore ──────────────────────────────────────────────────────────────────

export async function restoreVersion(id, { versionNumber, changeSummary, expectedEtag }) {
  const { data } = await client.post(`${BASE}/${id}/restore-version`, {
    version_number: versionNumber,
    change_summary: changeSummary,
    expected_etag: expectedEtag,   // optionaler ETag-Concurrency-Schutz (BUG-76-2)
  })
  return data
}

// ── Orphans (Admin + manage_orphan_stacks) ──────────────────────────────────

export async function fetchOrphans() {
  const { data } = await client.get(`${BASE}/orphans`)
  return data
}

export async function reassignOrphan(id, ownerUserId) {
  const { data } = await client.post(`${BASE}/orphans/${id}/reassign`, { owner_user_id: ownerUserId })
  return data
}

export async function purgeOrphan(id) {
  await client.delete(`${BASE}/orphans/${id}`)
}

// ── Phase 2b: Plan / Deploy / Destroy / Drift / Deployments / Resources ───────

/**
 * Erzeugt einen tofu-Plan (synchron). operation = 'apply' | 'destroy'.
 * @returns PlanResponse { plan_token, operation, summary:{create,change,destroy,replace,resources:[{name,action}]} }
 * Wirft den axios-Fehler weiter (403 RBAC, 412 Quota, 409 Lock/Definition).
 */
export async function planStack(id, operation = 'apply') {
  const { data } = await client.post(`${BASE}/${id}/plan`, null, { params: { operation } })
  return data
}

/**
 * Startet `tofu apply` als P3-Job (Body: Plan-Token).
 * @returns {{ kind: 'ok'|'pending', data }} – kind='pending' bei HTTP 202 (Approval).
 * 409 (Definition geändert / Lock) wird als axios-Fehler durchgereicht.
 */
export async function deployStack(id, planToken) {
  const resp = await client.post(`${BASE}/${id}/deploy`, { plan_token: planToken })
  if (resp.status === 202) return { kind: 'pending', data: resp.data }
  return { kind: 'ok', data: resp.data }
}

/** Startet `tofu destroy` als P3-Job. Siehe deployStack für Rückgabe-Semantik. */
export async function destroyStack(id, planToken) {
  const resp = await client.post(`${BASE}/${id}/destroy`, { plan_token: planToken })
  if (resp.status === 202) return { kind: 'pending', data: resp.data }
  return { kind: 'ok', data: resp.data }
}

/** Drift-Report (read-only `tofu plan`, nur Stack-eigene VMs). */
export async function fetchDrift(id) {
  const { data } = await client.post(`${BASE}/${id}/drift`)
  return data
}

export async function fetchDeployments(id) {
  const { data } = await client.get(`${BASE}/${id}/deployments`)
  return data
}

export async function fetchLiveResources(id) {
  const { data } = await client.get(`${BASE}/${id}/resources/live`)
  return data
}

// ── PROJ-85: Cloud-Init-Login (eigener verschlüsselter Store, getrennt vom YAML) ─

/**
 * Liest Stack-Default + Per-VM-Overrides. Passwort NIE im Klartext – nur
 * `password_set: bool` (AC-STORE-4). Overrides tragen `orphan` (EC-4).
 * @returns CloudInitConfigResponse { default, overrides[] }
 */
export async function getCloudInit(id) {
  const { data } = await client.get(`${BASE}/${id}/cloud-init`)
  return data
}

/**
 * Voll-Ersatz von Default + Overrides. Passwort write-only: leer/weggelassen =
 * unverändert (Merge, EC-6). 422 bei Lockout / static+count>1 / Key-Formfehler;
 * der axios-Fehler wird weitergereicht.
 */
export async function putCloudInit(id, body) {
  const { data } = await client.put(`${BASE}/${id}/cloud-init`, body)
  return data
}
