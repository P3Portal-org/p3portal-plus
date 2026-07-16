// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-101: gemeinsame Helfer für die Template-Replikation.

// Nutzerlesbare Fehlermeldung (analog lifecycleErrMsg). Server-Strings werden
// verbatim durchgereicht, sonst i18n-Fallback je Statuscode.
export function replicationErrMsg(err, t) {
  const s = err?.response?.status
  const d = err?.response?.data?.detail
  const detailStr = typeof d === 'string' ? d : null
  if (s === 403) return t('template_replication.err_403')
  if (s === 404) return t('template_replication.err_404')
  if (s === 409) return detailStr || t('template_replication.err_409')
  if (s === 422) return detailStr || t('template_replication.err_422')
  if (s === 503) return detailStr || t('template_replication.err_503')
  if (s === 502) return t('template_replication.err_502')
  return detailStr || t('template_replication.err_generic')
}

// Ist der Datastore `storage` auf `node` (aus der Preflight-Liste) shared?
export function isSharedStorage(preflight, node, storage) {
  const tn = (preflight?.targets ?? []).find((x) => x.node === node)
  if (!tn) return false
  const st = (tn.storages ?? []).find((x) => x.name === storage)
  return !!st?.shared
}

// Baut die Plan-Vorschau (client-seitig, spiegelt die Backend-Logik in
// start_replication): shared-Ziele mit demselben Datastore kollabieren zu EINER
// Operation (N→1); lokale Ziele → eine Operation pro Node.
//
// `selection` = [{ node, storage, newid }]  (nur Zeilen mit gewähltem storage)
// → { sharedOps: [{ storage, nodes: [...] }], localOps: [{ node, storage }] }
export function buildPlan(selection, preflight) {
  const sharedMap = new Map()   // storage → { storage, nodes: [] }
  const localOps = []
  for (const row of selection) {
    if (!row.storage) continue
    if (isSharedStorage(preflight, row.node, row.storage)) {
      if (!sharedMap.has(row.storage)) sharedMap.set(row.storage, { storage: row.storage, nodes: [] })
      sharedMap.get(row.storage).nodes.push(row.node)
    } else {
      localOps.push({ node: row.node, storage: row.storage })
    }
  }
  return { sharedOps: Array.from(sharedMap.values()), localOps }
}
