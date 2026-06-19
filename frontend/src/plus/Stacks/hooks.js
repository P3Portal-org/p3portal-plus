// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 1: React-Query-Hooks für Stacks.
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getNodeVmOptions, getLxcTemplates } from '../../api/cluster'
import { listImageStorages } from '../../api/vms'
import { listRefs, listMacros, listSecurityGroups } from '../../api/firewall'
import {
  fetchStacks,
  fetchStack,
  fetchVersions,
  fetchOrphans,
  deleteStack,
  reassignOrphan,
  purgeOrphan,
  planStack,
  deployStack,
  destroyStack,
  fetchDrift,
  fetchDeployments,
  fetchLiveResources,
  getCloudInit,
  putCloudInit,
} from './api'

// PROJ-76: Bridges/CPU-Typen/Tags eines Nodes (für die VM-Karten-Dropdowns).
// React Query dedupliziert identische Node-Abfragen über mehrere Karten hinweg.
export function useNodeVmOptions(node) {
  return useQuery({
    queryKey: ['stack-node-vm-options', node],
    queryFn: () => getNodeVmOptions(node),
    enabled: !!node,
    staleTime: 5 * 60_000,
  })
}

// PROJ-82: image-fähige Datastores eines Nodes (Datastore-Dropdown der Zusatz-
// Disks). Wiederverwendet den PROJ-81-Endpoint (admin→operator→viewer-Kette);
// bei fehlenden Rechten/offline liefert die Query nichts → Freitext-Fallback.
export function useImageStorages(node) {
  return useQuery({
    queryKey: ['stack-image-storages', node],
    queryFn: () => listImageStorages(node),
    enabled: !!node,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

// PROJ-86: installierte LXC-Templates (ostemplate-Tarballs) für das Container-
// Template-Dropdown. Reuse des PROJ-38-Endpoints `/api/cluster/lxc-templates`
// (Multi-Node-Fan-out); die LXC-Karte filtert `installed` node-abhängig und
// mappt auf die `volid`-File-ID (= bpg `template_file_id`). Freitext-Fallback
// bei fehlenden Rechten/offline.
export function useLxcTemplates() {
  return useQuery({
    queryKey: ['stack-lxc-templates'],
    queryFn: getLxcTemplates,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

// PROJ-91: Firewall-Editor-Daten (cluster-weit, best-effort) für die Regel-
// Dropdowns: Aliases/IPSets (refs), Macros, bestehende Security-Group-Namen.
// `installation=null` → Default-Node. Bei fehlenden Rechten/offline liefert die
// Query leere Listen → Freitext-Fallback (kein Editor-Block). Wird genau einmal
// im Editor geladen und an die Karten durchgereicht.
export function useStackFirewallRefs() {
  return useQuery({
    queryKey: ['stack-firewall-refs'],
    queryFn: async () => {
      const [refs, macros, sgs] = await Promise.all([
        listRefs(null).catch(() => []),
        listMacros(null).catch(() => []),
        listSecurityGroups(null).catch(() => ({ items: [] })),
      ])
      return {
        refs: Array.isArray(refs) ? refs : [],
        macros: Array.isArray(macros) ? macros : [],
        clusterSgNames: (sgs?.items ?? []).map((g) => g.group).filter(Boolean),
      }
    },
    staleTime: 5 * 60_000,
    retry: false,
  })
}

// ── Listen ────────────────────────────────────────────────────────────────

export function useStacks({ q, includeDeleted } = {}) {
  return useQuery({
    queryKey: ['stacks', q ?? '', includeDeleted ?? false],
    queryFn: () => fetchStacks({ q, includeDeleted }),
    staleTime: 30_000,
  })
}

export function useStack(id) {
  return useQuery({
    queryKey: ['stack', id],
    queryFn: () => fetchStack(id),
    enabled: !!id,
    staleTime: 30_000,
  })
}

export function useStackVersions(id) {
  return useQuery({
    queryKey: ['stack-versions', id],
    queryFn: () => fetchVersions(id),
    enabled: !!id,
    staleTime: 30_000,
  })
}

export function useOrphanStacks() {
  return useQuery({
    queryKey: ['stack-orphans'],
    queryFn: fetchOrphans,
    staleTime: 60_000,
  })
}

// ── Invalidierung ────────────────────────────────────────────────────────────

export function useInvalidateStacks() {
  const qc = useQueryClient()
  return (id) => {
    qc.invalidateQueries({ queryKey: ['stacks'] })
    if (id) {
      qc.invalidateQueries({ queryKey: ['stack', id] })
      qc.invalidateQueries({ queryKey: ['stack-versions', id] })
    }
  }
}

// ── Mutations ──────────────────────────────────────────────────────────────

export function useDeleteStack() {
  const invalidate = useInvalidateStacks()
  return useMutation({
    mutationFn: deleteStack,
    onSuccess: () => invalidate(),
  })
}

export function useReassignOrphan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ownerUserId }) => reassignOrphan(id, ownerUserId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['stack-orphans'] })
      qc.invalidateQueries({ queryKey: ['stacks'] })
    },
  })
}

export function usePurgeOrphan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: purgeOrphan,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['stack-orphans'] }),
  })
}

// ── Phase 2b: Deploy / Drift / Deployments / Resources ────────────────────────

export function useStackDeployments(id) {
  return useQuery({
    queryKey: ['stack-deployments', id],
    queryFn: () => fetchDeployments(id),
    enabled: !!id,
    staleTime: 10_000,
  })
}

export function useStackLiveResources(id) {
  return useQuery({
    queryKey: ['stack-resources-live', id],
    queryFn: () => fetchLiveResources(id),
    enabled: !!id,
    staleTime: 10_000,
  })
}

/** Plan (apply|destroy) – kein Cache, immer frisch über die Mutation. */
export function useStackPlan() {
  return useMutation({
    mutationFn: ({ id, operation }) => planStack(id, operation),
  })
}

/** apply – invalidiert Detail/Listen/Deployments nach Job-Start. */
export function useDeployStack() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, planToken }) => deployStack(id, planToken),
    onSuccess: (_res, { id }) => {
      qc.invalidateQueries({ queryKey: ['stack', id] })
      qc.invalidateQueries({ queryKey: ['stacks'] })
      qc.invalidateQueries({ queryKey: ['stack-deployments', id] })
    },
  })
}

/** destroy – gleiche Invalidierung wie deploy. */
export function useDestroyStack() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, planToken }) => destroyStack(id, planToken),
    onSuccess: (_res, { id }) => {
      qc.invalidateQueries({ queryKey: ['stack', id] })
      qc.invalidateQueries({ queryKey: ['stacks'] })
      qc.invalidateQueries({ queryKey: ['stack-deployments', id] })
    },
  })
}

// ── PROJ-85: Cloud-Init-Login ──────────────────────────────────────────────

/**
 * Cloud-Init-Konfig eines Stacks (Default + Overrides). `enabled: !!id` →
 * neue (noch nicht gespeicherte) Stacks fragen nichts ab. Liegt im eigenen
 * Store (nicht im YAML), daher eigene Query-Key + kurze staleTime.
 */
export function useStackCloudInit(id) {
  return useQuery({
    queryKey: ['stack-cloud-init', id],
    queryFn: () => getCloudInit(id),
    enabled: !!id,
    staleTime: 30_000,
  })
}

/** Voll-Ersatz der Cloud-Init-Konfig; invalidiert die eigene Query (Banner). */
export function usePutStackCloudInit() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }) => putCloudInit(id, body),
    onSuccess: (data, { id }) => {
      qc.setQueryData(['stack-cloud-init', id], data)
    },
  })
}

/** Drift on-demand – schreibt last_drift_state, daher Detail invalidieren. */
export function useStackDrift() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id) => fetchDrift(id),
    onSuccess: (_res, id) => {
      qc.invalidateQueries({ queryKey: ['stack', id] })
      qc.invalidateQueries({ queryKey: ['stacks'] })
    },
  })
}
