// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: Editor-Modell-Defaults + Payload-Bau (SoT = strukturiertes Modell).
// Schema gespiegelt aus backend/plus/ansible_editor/schemas.py.

/** Eine Definition-id aus dem Namen ableiten (gleiches Pattern wie das Backend:
 *  ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$, kein '..'). */
export function deriveId(name) {
  const slug = (name || '')
    .toLowerCase()
    .replace(/\.\./g, '-')
    .replace(/[^a-z0-9_.-]+/g, '-')
    .replace(/^[^a-z0-9]+/, '')
    .replace(/-+$/, '')
    .slice(0, 64)
  return slug
}

// Stabile FE-only Task-id (für React-keys / Reorder; vom Backend ignoriert,
// in buildPayload entfernt).
let _seq = 0
const uid = () => `t${++_seq}`

/** Leerer Task (ein ansible.builtin.*-Modul mit seinen Parametern). */
export function emptyTask() {
  return {
    _uid: uid(),
    name: '',
    module: '',
    params: {},
    when: null,
    loop: null,
    register_var: null,
    become: null,
    tags: [],
    notify: [],
  }
}

/** Geladenen Tasks (aus dem Sidecar) stabile _uids geben (Reorder-Stabilität). */
export function ensureTaskUids(model) {
  if (!model || !Array.isArray(model.tasks)) return model
  return { ...model, tasks: model.tasks.map((tk) => (tk._uid ? tk : { ...tk, _uid: uid() })) }
}

/** Leeres Editor-Modell (Default-Ziel guest). */
export function newModel() {
  return {
    schema_version: 1,
    id: '',
    name: '',
    description: '',
    category: null,
    required_role: 'operator',
    header: { targets: 'guest', become: false, gather_facts: false },
    tasks: [],
    side_files: {},
    _idTouched: false,
  }
}

/** Payload fürs Backend bauen — reinen FE-State (_idTouched / Task._uid) entfernen. */
export function buildPayload(model) {
  // eslint-disable-next-line no-unused-vars
  const { _idTouched, ...rest } = model
  return {
    ...rest,
    // eslint-disable-next-line no-unused-vars
    tasks: (rest.tasks || []).map(({ _uid, ...t }) => t),
  }
}
