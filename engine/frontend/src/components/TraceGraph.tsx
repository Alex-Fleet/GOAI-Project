import { useMemo } from 'react'
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import type { TraceStep } from '../types'

// 层顺序 = 图的 x 轴列；每层一个纵列，路径自左向右展开
const LAYER_ORDER = ['L1', 'L2', 'L3', 'L4', 'impact']
const LAYER_LABELS: Record<string, string> = {
  L1: '工艺图',
  L2: '判断点',
  L3: '设备内部',
  L4: '责任归属',
  impact: '波及',
}

interface GraphData {
  label: string
  id: string
  variant: 'ok' | 'bad' | 'neutral'
}

function TracingNode({ data }: NodeProps) {
  const d = data as unknown as GraphData
  return (
    <div className={`tn tn-${d.variant}`}>
      <Handle type="target" position={Position.Left} />
      <div className="tn-label">{d.label}</div>
      <div className="tn-id">{d.id}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

const nodeTypes = { tracing: TracingNode }

interface Props {
  steps: TraceStep[]
  status: string
}

export default function TraceGraph({ steps, status }: Props) {
  const { nodes, edges } = useMemo(() => buildGraph(steps), [steps])

  return (
    <div className="trace-graph">
      <div className="trace-toolbar">
        <span className="trace-status" data-status={status}>
          {status}
        </span>
        <span className="trace-legend">
          {LAYER_ORDER.filter((l) => LAYER_LABELS[l]).map((l) => (
            <span key={l} className="legend-item">
              {l}: {LAYER_LABELS[l]}
            </span>
          ))}
        </span>
      </div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        nodesConnectable={false}
        nodesDraggable={false}
        elementsSelectable
      >
        <Background gap={18} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}

function buildGraph(steps: TraceStep[]): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = []
  const edges: Edge[] = []
  const nodeMap = new Map<string, Node>()
  const colCount: Record<number, number> = {}
  const relSeen = new Set<string>()

  for (const step of steps) {
    const col = Math.max(0, LAYER_ORDER.indexOf(step.layer))
    const variant: GraphData['variant'] =
      step.verdict === null ? 'neutral' : step.verdict.passed ? 'ok' : 'bad'
    for (const edge of step.path) {
      for (const ref of [edge.src, edge.dst]) {
        const key = `${ref.label}:${ref.id}`
        if (!nodeMap.has(key)) {
          const y = (colCount[col] ?? 0) * 96
          colCount[col] = (colCount[col] ?? 0) + 1
          const node: Node = {
            id: key,
            type: 'tracing',
            position: { x: col * 250, y },
            data: { label: ref.label, id: ref.id, variant } satisfies GraphData,
          }
          nodeMap.set(key, node)
          nodes.push(node)
        }
      }
      const eid = `${edge.src.label}:${edge.src.id}|${edge.rel}|${edge.dst.label}:${edge.dst.id}`
      if (!relSeen.has(eid)) {
        relSeen.add(eid)
        edges.push({
          id: eid,
          source: `${edge.src.label}:${edge.src.id}`,
          target: `${edge.dst.label}:${edge.dst.id}`,
          label: edge.rel,
          type: 'smoothstep',
        })
      }
    }
  }
  return { nodes, edges }
}
