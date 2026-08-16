import { useEffect, useMemo, useRef, useState } from 'react'
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, type Simulation } from 'd3-force'
import type { SimulationNodeDatum } from 'd3-force'

import type { OntoEdge, OntoNode } from '../types'

interface Props {
  nodes: OntoNode[]
  edges: OntoEdge[]
  highlightNodes?: Set<string>
  highlightEdges?: Set<string>
}

interface SimNode extends SimulationNodeDatum {
  id: string
  label: string
  name: string
}

interface SimEdge {
  source: string | SimNode
  target: string | SimNode
  rel: string
  key: string
}

const LABEL_CN: Record<string, string> = {
  Product: '产品',
  Process: '工序',
  Equipment: '设备',
  Material: '材质',
  Component: '部件',
  Property: '参数',
  Supplier: '供应商',
  Clause: '条款',
  Contract: '合同',
  PurchaseOrder: '订单',
  Customer: '客户',
  Symptom: '症状',
  Fault: '故障',
  Defect: '缺陷',
  Batch: '批次',
}

const TYPE_COLOR: Record<string, string> = {
  Product: '#e7e5e4',
  Process: '#e7e5e4',
  Equipment: '#d6d3d1',
  Material: '#e7e5e4',
  Component: '#d6d3d1',
  Property: '#edf2f7',
  Supplier: '#e2e8f0',
  Clause: '#e2e8f0',
  Contract: '#dbeafe',
  Order: '#dbeafe',
  Customer: '#dbeafe',
  Symptom: '#fdba74',
  Fault: '#fca5a5',
  Defect: '#fecaca',
}

interface View {
  scale: number
  tx: number
  ty: number
}

// 视口 = 固定逻辑窗口（SVG viewBox）；画布 = 节点世界坐标（可大于窗口，滚动/拖动浏览）
const VIEW_W = 1000
const VIEW_H = 600

function fitView(nodes: SimNode[]): View {
  if (nodes.length === 0) return { scale: 1, tx: 0, ty: 0 }
  const xs = nodes.map((n) => n.x ?? 0)
  const ys = nodes.map((n) => n.y ?? 0)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const scale = Math.min(VIEW_W / Math.max(1, maxX - minX), VIEW_H / Math.max(1, maxY - minY)) * 0.92
  const tx = -(minX * scale) + (VIEW_W - (maxX - minX) * scale) / 2
  const ty = -(minY * scale) + (VIEW_H - (maxY - minY) * scale) / 2
  return { scale, tx, ty }
}

export default function OntologyGraph({ nodes, edges, highlightNodes, highlightEdges }: Props) {
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }>>(new Map())
  const [view, setView] = useState<View>({ scale: 1, tx: 0, ty: 0 })
  const [selected, setSelected] = useState<string | null>(null)
  const simRef = useRef<Simulation<SimNode, undefined> | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const dragRef = useRef<{
    type: 'pan' | 'node'
    id?: string
    startX: number
    startY: number
    nodeX?: number
    nodeY?: number
  } | null>(null)

  const simNodes: SimNode[] = useMemo(
    () => nodes.map((n) => ({ id: n.id, label: n.label, name: String(n.name ?? n.id) })),
    [nodes],
  )
  const simEdges: SimEdge[] = useMemo(
    () =>
      edges.map((e) => ({
        source: e.source,
        target: e.target,
        rel: e.rel,
        key: `${e.source}|${e.rel}|${e.target}`,
      })),
    [edges],
  )

  useEffect(() => {
    const sim = forceSimulation(simNodes)
      .force('link', forceLink(simEdges).id((d) => (d as SimNode).id).distance(70).strength(0.4))
      .force('charge', forceManyBody().strength(-70))
      .force('center', forceCenter(0, 0))
      .force('collide', forceCollide(13))
      .on('tick', () => {
        const next = new Map(simNodes.map((n) => [n.id, { x: n.x ?? 0, y: n.y ?? 0 }]))
        setPositions(next)
      })
      // 布局收敛后 fit 一次初始视图（之后用户滚动/拖动浏览，不再自动改）
      .on('end', () => {
        setView(fitView(simNodes))
      })
    simRef.current = sim
    return () => {
      sim.stop()
    }
  }, [simNodes, simEdges])

  // ---- 画布：滚轮缩放（围绕鼠标） + 空白拖拽平移 ----

  // 滚轮缩放：原生非 passive 监听，preventDefault 阻止页面随滚轮上下滚动
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const onWheelNative = (e: WheelEvent) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      const mx = e.clientX - rect.left
      const my = e.clientY - rect.top
      const factor = e.deltaY < 0 ? 1.12 : 0.89
      setView((v) => {
        const scale = Math.min(5, Math.max(0.25, v.scale * factor))
        const k = scale / v.scale
        return { scale, tx: mx - (mx - v.tx) * k, ty: my - (my - v.ty) * k }
      })
    }
    el.addEventListener('wheel', onWheelNative, { passive: false })
    return () => el.removeEventListener('wheel', onWheelNative)
  }, [])

  function onBgDown(e: React.PointerEvent) {
    dragRef.current = { type: 'pan', startX: e.clientX, startY: e.clientY }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  function onBgMove(e: React.PointerEvent) {
    const d = dragRef.current
    if (d && d.type === 'pan') {
      setView((v) => ({ ...v, tx: v.tx + e.clientX - d.startX, ty: v.ty + e.clientY - d.startY }))
      dragRef.current = { type: 'pan', startX: e.clientX, startY: e.clientY }
    }
  }
  function onBgUp() {
    dragRef.current = null
  }

  // ---- 节点：拖拽 + 点击看详情 ----

  function onNodeDown(e: React.PointerEvent, n: SimNode) {
    e.stopPropagation()
    const p = positions.get(n.id)
    dragRef.current = { type: 'node', id: n.id, startX: e.clientX, startY: e.clientY, nodeX: p?.x ?? 0, nodeY: p?.y ?? 0 }
    e.currentTarget.setPointerCapture(e.pointerId)
    simRef.current?.alphaTarget(0.3).restart()
  }
  function onNodeMove(e: React.PointerEvent, n: SimNode) {
    const d = dragRef.current
    if (d && d.type === 'node' && d.id === n.id) {
      const node = simNodes.find((s) => s.id === n.id)
      if (node && d.nodeX !== undefined && d.nodeY !== undefined) {
        node.fx = d.nodeX + e.clientX - d.startX
        node.fy = d.nodeY + e.clientY - d.startY
      }
    }
  }
  function onNodeUp(n: SimNode) {
    if (dragRef.current?.type === 'node') {
      const node = simNodes.find((s) => s.id === n.id)
      if (node) {
        node.fx = null
        node.fy = null
      }
      dragRef.current = null
      simRef.current?.alphaTarget(0)
    }
  }
  function onNodeClick(e: React.MouseEvent, n: SimNode) {
    e.stopPropagation()
    if (dragRef.current) return // 拖拽结束的 click 忽略
    setSelected(selected === n.id ? null : n.id)
  }

  // 选中节点详情：ABox（属性）+ TBox（出边候选 / 入边关系）
  const selInfo = useMemo(() => {
    if (!selected) return null
    const node = nodes.find((n) => n.id === selected)
    if (!node) return null
    const out = simEdges
      .filter((e) => (typeof e.source === 'string' ? e.source : e.source.id) === selected)
      .map((e) => ({ rel: e.rel, dst: typeof e.target === 'string' ? e.target : e.target.id }))
    const inn = simEdges
      .filter((e) => (typeof e.target === 'string' ? e.target : e.target.id) === selected)
      .map((e) => ({ rel: e.rel, src: typeof e.source === 'string' ? e.source : e.source.id }))
    const props = Object.entries(node).filter(([k]) => !['id', 'label', 'name'].includes(k))
    return { node, out, inn, props }
  }, [selected, nodes, simEdges])

  const isNodeHit = (id: string) => highlightNodes?.has(id) ?? false
  const isEdgeHit = (e: SimEdge) => {
    const src = typeof e.source === 'string' ? e.source : e.source.id
    const dst = typeof e.target === 'string' ? e.target : e.target.id
    return highlightEdges?.has(`${src}|${e.rel}|${dst}`) ?? false
  }

  return (
    <div className="onto-wrap">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="onto-svg"
        onPointerDown={onBgDown}
        onPointerMove={onBgMove}
        onPointerUp={onBgUp}
      >
        <g transform={`translate(${view.tx},${view.ty}) scale(${view.scale})`}>
          {simEdges.map((e) => {
            const src = typeof e.source === 'string' ? positions.get(e.source) : e.source
            const dst = typeof e.target === 'string' ? positions.get(e.target) : e.target
            if (!src || !dst) return null
            const hit = isEdgeHit(e)
            return (
              <line key={e.key} x1={src.x} y1={src.y} x2={dst.x} y2={dst.y} className={`onto-edge${hit ? ' is-hit' : ''}`} />
            )
          })}
          {simNodes.map((n) => {
            const p = positions.get(n.id)
            if (!p) return null
            const hit = isNodeHit(n.id)
            return (
              <g
                key={n.id}
                transform={`translate(${p.x},${p.y})`}
                className={`onto-node${hit ? ' is-hit' : ''}${selected === n.id ? ' is-selected' : ''}`}
                onPointerDown={(e) => onNodeDown(e, n)}
                onPointerMove={(e) => onNodeMove(e, n)}
                onPointerUp={() => onNodeUp(n)}
                onClick={(e) => onNodeClick(e, n)}
              >
                <circle
                  r={10}
                  fill={hit ? '#b45309' : (TYPE_COLOR[n.label] ?? '#d6d3d1')}
                  stroke={hit ? '#1c1c1a' : selected === n.id ? '#b45309' : '#a8a29e'}
                  strokeWidth={hit ? 2 : selected === n.id ? 1.8 : 0.8}
                />
                <text className="onto-node-label" dy={4} fill={hit ? '#fff' : '#1c1c1a'}>
                  {LABEL_CN[n.label] ?? n.label}
                </text>
                <text className="onto-node-sub" y={22} fill="#6b6b66">
                  {n.name.length > 6 ? `${n.name.slice(0, 6)}…` : n.name}
                </text>
              </g>
            )
          })}
        </g>
      </svg>
      {selInfo && (
        <aside className="onto-detail">
          <button className="onto-close" onClick={() => setSelected(null)}>×</button>
          <div className="onto-detail-title">
            {selInfo.node.label} · {selInfo.node.name}
          </div>
          <div className="onto-detail-sec">
            <div className="onto-detail-head">ABox（个体属性）</div>
            <dl className="onto-props">
              {selInfo.props.length === 0 && <dd>（无额外属性）</dd>}
              {selInfo.props.map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{String(v)}</dd>
                </div>
              ))}
            </dl>
          </div>
          {selInfo.out.length > 0 && (
            <div className="onto-detail-sec">
              <div className="onto-detail-head">TBox（出边候选 / 关系）</div>
              <ul className="onto-rel">
                {selInfo.out.map((o, i) => (
                  <li key={i}>
                    <span className="rel-type">{o.rel}</span> → {o.dst}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {selInfo.inn.length > 0 && (
            <div className="onto-detail-sec">
              <div className="onto-detail-head">入边</div>
              <ul className="onto-rel">
                {selInfo.inn.map((o, i) => (
                  <li key={i}>
                    {o.src} <span className="rel-type">{o.rel}</span> →
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      )}
    </div>
  )
}
