// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: API-Helper für den Ansible Visual Editor.
// 9 EPs unter /api/ansible-editor (alle Plus-404 im Core + require_admin).
import client from '../../api/client'

const BASE = '/api/ansible-editor'

// ── Liste / Detail ───────────────────────────────────────────────────────────

/** Liste editor-verwalteter Definitionen (Marker-gefiltert, AC-ROUND-1). */
export async function listDefinitions() {
  const { data } = await client.get(`${BASE}/definitions`)
  return data
}

/** Strukturiertes Modell aus dem .p3editor.json-Sidecar laden (Wieder-Bearbeiten). */
export async function getDefinition(id) {
  const { data } = await client.get(`${BASE}/definitions/${id}`)
  return data
}

// ── Erstellen / Bearbeiten / Löschen ─────────────────────────────────────────

/**
 * Neue Definition (Modell → ansible/<id>/ + Sidecar + <id>.yml + meta.yaml).
 * 400 (validation_failed) und 409 (definition_exists/foreign_definition_exists)
 * werden als axios-Fehler durchgereicht, damit der Aufrufer sie klar meldet.
 * @returns DefinitionSummary
 */
export async function createDefinition(model) {
  const { data } = await client.post(`${BASE}/definitions`, model)
  return data
}

/** Bearbeiten (deterministisch überschreiben, EC-12). 404 wenn nicht editor-eigen. */
export async function updateDefinition(id, model) {
  const { data } = await client.put(`${BASE}/definitions/${id}`, model)
  return data
}

/** Löschen (nur editor-eigene; 409 foreign_definition wird durchgereicht, EC-6). */
export async function deleteDefinition(id) {
  await client.delete(`${BASE}/definitions/${id}`)
}

// ── Module & Schema (dynamischer ansible-doc-Cache) ──────────────────────────

/** Liste aller ansible.builtin-Module (name + short_description), AC-MOD-1. */
export async function listModules() {
  const { data } = await client.get(`${BASE}/modules`)
  return data
}

/** Bereinigtes Parameter-Schema eines Moduls (AC-MOD-2, generischer Renderer). */
export async function getModuleSchema(name) {
  const { data } = await client.get(`${BASE}/modules/${name}/schema`)
  return data
}

// ── Validieren / Vorschau ────────────────────────────────────────────────────

/**
 * hard_validate (gegen den Schema-Cache) + semantische Warnungen, ohne zu
 * speichern. Liefert errors[] (blockierend) + warnings[] (nicht-blockierend).
 * @returns ValidationResult { ok, errors[], warnings[] }
 */
export async function validateDefinition(model) {
  const { data } = await client.post(`${BASE}/validate`, model)
  return data
}

/**
 * Generierte read-only Projektion ohne zu speichern (YAML-Tab + meta.yaml +
 * Nebendatei-Liste).
 * @returns PreviewResult { yaml, meta_yaml, files{name→inhalt}, warnings[] }
 */
export async function previewDefinition(model) {
  const { data } = await client.post(`${BASE}/preview`, model)
  return data
}
