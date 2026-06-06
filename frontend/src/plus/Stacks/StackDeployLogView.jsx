// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-76 Phase 2b: Live-Log eines Deploy/Destroy-Laufs (AC-2B-UI-3).
// Wiederverwendung des bestehenden Job-Log-WebSockets (useJobLog) — keine neue Dep.
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useJobLog } from '../../hooks/useJobs'

const STATUS_BADGE = {
  pending: 'bg-portal-bg3 text-portal-text2',
  running: 'bg-portal-info/15 text-portal-info',
  success: 'bg-portal-success/15 text-portal-success',
  failed:  'bg-portal-danger/15 text-portal-danger',
}

export default function StackDeployLogView({ jobId }) {
  const { t } = useTranslation()
  const { lines, status, connected } = useJobLog(jobId)
  const logRef = useRef(null)

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [lines])

  return (
    <div className="flex flex-col min-h-0 flex-1">
      <div className="flex items-center justify-between px-1 pb-2 shrink-0">
        <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${STATUS_BADGE[status] ?? STATUS_BADGE.pending}`}>
          {status === 'running' && (
            <svg className="inline animate-spin w-3 h-3 mr-1 -mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M21 12a9 9 0 1 1-6.219-8.56" />
            </svg>
          )}
          {status}
        </span>
        <span className={`text-xs ${connected ? 'text-portal-success' : 'text-portal-text3'}`}>
          {connected ? `● ${t('stacks.deploy.log_live')}` : `○ ${t('stacks.deploy.log_disconnected')}`}
        </span>
      </div>
      <div ref={logRef} className="flex-1 overflow-y-auto bg-zinc-950 rounded-md p-3 font-mono text-xs text-zinc-300 leading-relaxed min-h-[200px] max-h-[50vh]">
        {lines.length === 0
          ? <span className="text-zinc-600">{t('stacks.deploy.log_waiting')}</span>
          : lines.map((line, i) => <div key={i} className="whitespace-pre-wrap break-all">{line}</div>)
        }
      </div>
    </div>
  )
}
