// p3portal.org
// PROJ-101: Unit-Tests für die reine Plan-/Storage-Helferlogik.
import { describe, it, expect } from 'vitest'
import { buildPlan, isSharedStorage, replicationErrMsg } from './replicationHelpers'

const PREFLIGHT = {
  targets: [
    { node: 'pve2', storages: [{ name: 'local-lvm', shared: false }, { name: 'ceph', shared: true }] },
    { node: 'pve3', storages: [{ name: 'local-lvm', shared: false }, { name: 'ceph', shared: true }] },
  ],
}

describe('isSharedStorage', () => {
  it('erkennt shared Storage', () => {
    expect(isSharedStorage(PREFLIGHT, 'pve2', 'ceph')).toBe(true)
  })
  it('erkennt lokalen Storage als nicht-shared', () => {
    expect(isSharedStorage(PREFLIGHT, 'pve2', 'local-lvm')).toBe(false)
  })
  it('unbekannte Node/Storage → false', () => {
    expect(isSharedStorage(PREFLIGHT, 'pveX', 'ceph')).toBe(false)
    expect(isSharedStorage(PREFLIGHT, 'pve2', 'nope')).toBe(false)
  })
})

describe('buildPlan', () => {
  it('kollabiert shared-Ziele mit gleichem Datastore zu EINER Op (N→1)', () => {
    const selection = [
      { node: 'pve2', storage: 'ceph' },
      { node: 'pve3', storage: 'ceph' },
    ]
    const plan = buildPlan(selection, PREFLIGHT)
    expect(plan.sharedOps).toHaveLength(1)
    expect(plan.sharedOps[0].storage).toBe('ceph')
    expect(plan.sharedOps[0].nodes.sort()).toEqual(['pve2', 'pve3'])
    expect(plan.localOps).toHaveLength(0)
  })

  it('lokale Ziele → eine Op pro Node', () => {
    const selection = [
      { node: 'pve2', storage: 'local-lvm' },
      { node: 'pve3', storage: 'local-lvm' },
    ]
    const plan = buildPlan(selection, PREFLIGHT)
    expect(plan.sharedOps).toHaveLength(0)
    expect(plan.localOps).toHaveLength(2)
    expect(plan.localOps.map((o) => o.node).sort()).toEqual(['pve2', 'pve3'])
  })

  it('mischt shared + lokal korrekt', () => {
    const selection = [
      { node: 'pve2', storage: 'ceph' },
      { node: 'pve3', storage: 'local-lvm' },
    ]
    const plan = buildPlan(selection, PREFLIGHT)
    expect(plan.sharedOps).toHaveLength(1)
    expect(plan.localOps).toHaveLength(1)
    expect(plan.localOps[0].node).toBe('pve3')
  })

  it('überspringt Zeilen ohne gewählten Storage', () => {
    const selection = [{ node: 'pve2', storage: '' }, { node: 'pve3', storage: 'ceph' }]
    const plan = buildPlan(selection, PREFLIGHT)
    expect(plan.sharedOps).toHaveLength(1)
    expect(plan.localOps).toHaveLength(0)
  })
})

describe('replicationErrMsg', () => {
  const t = (k) => k
  it('reicht Server-Detail bei 409/422 verbatim durch', () => {
    const err = { response: { status: 409, data: { detail: 'A replication is running' } } }
    expect(replicationErrMsg(err, t)).toBe('A replication is running')
  })
  it('nutzt i18n-Fallback bei 403 (kein Server-String)', () => {
    const err = { response: { status: 403, data: {} } }
    expect(replicationErrMsg(err, t)).toBe('template_replication.err_403')
  })
  it('generischer Fallback ohne Response', () => {
    expect(replicationErrMsg({}, t)).toBe('template_replication.err_generic')
  })
})
