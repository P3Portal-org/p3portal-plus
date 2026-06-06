// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: Stacks-Modul-Exports (Plus-only).
// Die 4 Core-Konsum-Punkte (3 Route-Komponenten + Orphan-Tab) werden in
// frontend/src/plus/index.js via React.lazy in die Plus-Registry gehoben.
// Die übrigen Komponenten werden Plus→Plus direkt importiert.
export { default as StacksListPage } from './StacksListPage'
export { default as StackEditorPage } from './StackEditorPage'
export { default as StackDetailPage } from './StackDetailPage'
export { default as OrphanStacksTab } from './OrphanStacksTab'
