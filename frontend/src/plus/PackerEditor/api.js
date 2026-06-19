// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-92: API-Helper für den Packer Visual Editor.
// 7 EPs unter /api/packer-editor (alle Plus-404 im Core + require_admin).
import client from '../../api/client'

const BASE = '/api/packer-editor'

// ── Liste / Detail ───────────────────────────────────────────────────────────

/** Liste editor-verwalteter Definitionen (Marker-gefiltert, AC-ROUND-2). */
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
 * Neue Definition (Modell → Verzeichnis + Sidecar + generierte Dateien).
 * 409 (definition_exists / foreign_definition_exists) wird als axios-Fehler
 * durchgereicht, damit der Aufrufer die Kollision klar melden kann.
 * @returns DefinitionSummary
 */
export async function createDefinition(model) {
  const { data } = await client.post(`${BASE}/definitions`, model)
  return data
}

/** Bearbeiten (deterministisch überschreiben, EC-2). 404 wenn nicht editor-eigen. */
export async function updateDefinition(id, model) {
  const { data } = await client.put(`${BASE}/definitions/${id}`, model)
  return data
}

/** Löschen (nur editor-eigene; 409 foreign_definition wird durchgereicht, EC-11). */
export async function deleteDefinition(id) {
  await client.delete(`${BASE}/definitions/${id}`)
}

// ── Validieren / Vorschau ────────────────────────────────────────────────────

/**
 * Pydantic-422 (Pflichtfelder/Typen) wird als axios-Fehler geworfen; bei Erfolg
 * liefert der Body nur die nicht-blockierenden semantischen Warnungen.
 * @returns ValidationResult { ok, warnings[] }
 */
export async function validateDefinition(model) {
  const { data } = await client.post(`${BASE}/validate`, model)
  return data
}

/**
 * Generierte read-only Projektion ohne zu speichern (JSON-Tab + Installer-Freitext).
 * @returns PreviewResult { hcl, files{name→inhalt}, meta_yaml, warnings[] }
 */
export async function previewDefinition(model) {
  const { data } = await client.post(`${BASE}/preview`, model)
  return data
}
