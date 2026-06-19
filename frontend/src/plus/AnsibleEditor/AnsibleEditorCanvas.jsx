// SPDX-License-Identifier: LicenseRef-P3-Plus
// SPDX-FileCopyrightText: Copyright (C) 2026 rootq <contact@rootq.de>
// === P3 PLUS – PROPRIETARY ===
// Licensed under LICENSE-PLUS (see repo root)
// Modification/Redistribution prohibited (see LICENSE-PLUS for security-patch exception)
// Contact: license@p3portal.org

// p3portal.org
// PROJ-93: n8n-artige Canvas für den Ansible Visual Editor (React Flow, bereits
// im Projekt aus PROJ-75 — keine neue Dep). Play-Start-Node + linear verkettete
// Task-Nodes; Verbindungslinien = Task-Reihenfolge (kein Branch — `when` bleibt
// ein Task-Parameter). Das strukturierte Modell ist die Wahrheit; die Canvas ist
// nur eine View darauf. Die Nodes werden bei jedem Modell-Change neu aus dem
// Modell aufgebaut, **Drag-Positionen bleiben erhalten** (pos-Map aus dem
// vorherigen Node-State) — sonst springt das Layout bei jeder Eingabe.
import { useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import ReactFlow, {
  Background,
  Controls,
  Panel,
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  useReactFlow,
} from 'reactflow'
import 'reactflow/dist/style.css'
import PlayNode from './nodes/PlayNode'
import TaskNode from './nodes/TaskNode'
import { emptyTask } from './model'

const NODE_TYPES = { play: PlayNode, task: TaskNode }

// Ansicht neu einpassen, wenn sich die Node-Anzahl ODER ein Modul ändert (der
// Node wächst dann nach dem async Schema-Load) — aber NICHT bei jeder
// Feld-Eingabe (sonst springt die Ansicht). Kleiner Delay, damit der Node erst
// seine neue Höhe bekommt. Muster PROJ-75.
function FitOnChange({ depKey }) {
  const { fitView } = useReactFlow()
  useEffect(() => {
    const id = setTimeout(() => fitView({ padding: 0.2, duration: 300, maxZoom: 1 }), 220)
    return () => clearTimeout(id)
  }, [depKey, fitView])
  return null
}

function CanvasInner({ model, onModelChange }) {
  const { t } = useTranslation()
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  // ── Modell-Mutationen (funktionale Updates → stabile Callbacks) ─────────────
  const patchHeader = useCallback(
    (partial) => onModelChange((m) => ({ ...m, header: { ...m.header, ...partial } })),
    [onModelChange],
  )
  const patchTask = useCallback(
    (uid, patch) => onModelChange((m) => ({ ...m, tasks: m.tasks.map((tk) => (tk._uid === uid ? { ...tk, ...patch } : tk)) })),
    [onModelChange],
  )
  const setParam = useCallback(
    (uid, name, value) => onModelChange((m) => ({
      ...m,
      tasks: m.tasks.map((tk) => {
        if (tk._uid !== uid) return tk
        const params = { ...tk.params }
        if (value === undefined) delete params[name]
        else params[name] = value
        return { ...tk, params }
      }),
    })),
    [onModelChange],
  )
  const removeTask = useCallback(
    (uid) => onModelChange((m) => ({ ...m, tasks: m.tasks.filter((tk) => tk._uid !== uid) })),
    [onModelChange],
  )
  const moveTask = useCallback(
    (uid, dir) => onModelChange((m) => {
      const i = m.tasks.findIndex((tk) => tk._uid === uid)
      const j = dir === 'up' ? i - 1 : i + 1
      if (i < 0 || j < 0 || j >= m.tasks.length) return m
      const tasks = [...m.tasks]
      ;[tasks[i], tasks[j]] = [tasks[j], tasks[i]]
      return { ...m, tasks }
    }),
    [onModelChange],
  )
  const addAfter = useCallback(
    (uid) => onModelChange((m) => {
      const i = m.tasks.findIndex((tk) => tk._uid === uid)
      const tasks = [...m.tasks]
      tasks.splice(i + 1, 0, emptyTask())
      return { ...m, tasks }
    }),
    [onModelChange],
  )
  const addTask = useCallback(
    () => onModelChange((m) => ({ ...m, tasks: [...m.tasks, emptyTask()] })),
    [onModelChange],
  )

  // ── Modell → Nodes/Edges synchronisieren (Positions-Erhalt) ─────────────────
  useEffect(() => {
    setNodes((prev) => {
      const pos = new Map(prev.map((n) => [n.id, n.position]))
      const out = [{
        id: 'play',
        type: 'play',
        position: pos.get('play') ?? { x: 0, y: 80 },
        data: { header: model.header, onHeaderChange: patchHeader },
      }]
      model.tasks.forEach((task, i) => {
        out.push({
          id: task._uid,
          type: 'task',
          position: pos.get(task._uid) ?? { x: 300 + i * 360, y: 60 },
          data: {
            task,
            index: i,
            total: model.tasks.length,
            patchTask: (patch) => patchTask(task._uid, patch),
            setParam: (name, value) => setParam(task._uid, name, value),
            removeTask: () => removeTask(task._uid),
            moveTask: (dir) => moveTask(task._uid, dir),
            addAfter: () => addAfter(task._uid),
          },
        })
      })
      return out
    })
    setEdges(model.tasks.map((task, i) => ({
      id: `e-${task._uid}`,
      source: i === 0 ? 'play' : model.tasks[i - 1]._uid,
      target: task._uid,
      type: 'smoothstep',
      style: { stroke: 'var(--portal-border, #cbd5e1)', strokeWidth: 1.5 },
    })))
  }, [model, setNodes, setEdges, patchHeader, patchTask, setParam, removeTask, moveTask, addAfter])

  return (
    <div className="h-[72vh] min-h-[560px] rounded-lg border border-portal-border bg-portal-bg2/30 overflow-hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.25, maxZoom: 1 }}
        minZoom={0.3}
        maxZoom={1.5}
        nodesConnectable={false}
        deleteKeyCode={null}
        proOptions={{ hideAttribution: false }}
      >
        <FitOnChange depKey={`${model.tasks.length}:${model.tasks.map((tk) => tk.module).join(',')}`} />
        <Background gap={18} color="var(--portal-border, #e5e7eb)" />
        <Controls position="bottom-right" showInteractive={false} />
        <Panel position="top-left">
          <button type="button" onClick={addTask} className="btn-primary text-xs flex items-center gap-1">
            + {t('ansible_editor.canvas.add_task')}
          </button>
        </Panel>
        {model.tasks.length === 0 && (
          <Panel position="top-center">
            <p className="text-xs text-portal-text3 mt-2 px-3 py-1.5 rounded-md bg-portal-bg2/80 border border-portal-border">
              {t('ansible_editor.canvas.empty_hint')}
            </p>
          </Panel>
        )}
      </ReactFlow>
    </div>
  )
}

export default function AnsibleEditorCanvas(props) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  )
}
