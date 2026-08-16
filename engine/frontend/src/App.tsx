import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import { analyzeBatch, getChain, getOntology, getSamples } from './api'
import AttributionPanel from './components/AttributionPanel'
import BatchTable, { type BatchRow } from './components/BatchTable'
import ChatPane from './components/ChatPane'
import OntologyGraph from './components/OntologyGraph'
import TraceGraph from './components/TraceGraph'
import type { OntoData, SampleMeta, TraceChain } from './types'

export default function App() {
  const [ontology, setOntology] = useState<OntoData>({ nodes: [], edges: [] })
  const [batchRows, setBatchRows] = useState<BatchRow[]>([])
  const [activeRoot, setActiveRoot] = useState<string | null>(null)
  const [chain, setChain] = useState<TraceChain | null>(null)
  const [selectedSample, setSelectedSample] = useState<SampleMeta | null>(null)
  const [messages, setMessages] = useState<{ role: string; text: string }[]>([])
  const [batchBusy, setBatchBusy] = useState(false)
  const abortRef = useRef<() => void>(() => {})

  useEffect(() => {
    getSamples().catch((e) => console.error('加载样本失败:', e))
    getOntology().then(setOntology).catch((e) => console.error('加载本体失败:', e))
    runBatch()
  }, [])

  useEffect(() => () => abortRef.current(), [])

  const runBatch = useCallback(async () => {
    setBatchBusy(true)
    try {
      const rows = await analyzeBatch(undefined, true)
      setBatchRows(rows)
      setMessages((m) => [
        ...m,
        {
          role: 'agent',
          text: `已分析 ${rows.length} 个零件（CiP-DMD 气缸底 / DMC-50H 铣床，真实工艺信号）。系统从数据中归因出：${summarize(rows)}。点击上方问题按钮或表格行查看推理链。`,
        },
      ])
    } catch (e) {
      setMessages((m) => [...m, { role: 'error', text: `批量分析失败：${String(e)}` }])
    } finally {
      setBatchBusy(false)
    }
  }, [])

  // 归因问题统计（推理后动态出现，非预置答案）
  const rootSummary = useMemo(() => {
    const groups: Record<string, number> = {}
    for (const r of batchRows) {
      const key = r.status === 'PASS' ? '正常' : r.locked ?? '无法归因'
      groups[key] = (groups[key] ?? 0) + 1
    }
    return groups
  }, [batchRows])

  const filteredRows = useMemo(() => {
    if (!activeRoot) return batchRows
    if (activeRoot === '正常') return batchRows.filter((r) => r.status === 'PASS')
    if (activeRoot === '无法归因') return batchRows.filter((r) => r.status === 'FAILED')
    return batchRows.filter((r) => r.locked === activeRoot)
  }, [batchRows, activeRoot])

  const handlePickRoot = useCallback(
    async (root: string) => {
      setActiveRoot(root)
      setMessages((m) => [...m, { role: 'user', text: `查看归因类别：${root}` }])
      // 展示该类一个代表性推理链
      const rows = root === '正常' ? batchRows.filter((r) => r.status === 'PASS') : root === '无法归因' ? batchRows.filter((r) => r.status === 'FAILED') : batchRows.filter((r) => r.locked === root)
      const row = rows.find((r) => r.chain_id) ?? rows[0]
      if (row && row.chain_id) await loadChain(row)
    },
    [batchRows],
  )

  const handleSelectRow = useCallback((row: BatchRow) => {
    if (row.chain_id) void loadChain(row)
  }, [batchRows])

  const loadChain = useCallback(
    async (row: BatchRow) => {
      if (!row.chain_id) return
      setSelectedSample({
        part_id: row.part_id,
        official_anomaly: row.official_anomaly,
        official_name: row.official_name,
        surface_roughness: row.surface_roughness ?? 0,
        saw_weight: null,
        signal: null,
        symptom: row.symptom,
      })
      try {
        const c = await getChain(row.chain_id)
        setChain(c)
      } catch (e) {
        setMessages((m) => [...m, { role: 'error', text: `加载推理链失败：${String(e)}` }])
      }
    },
    [],
  )

  // 推理点亮
  const highlight = useMemo(() => {
    const nodes = new Set<string>()
    const edges = new Set<string>()
    for (const step of chain?.steps ?? []) {
      for (const e of step.path) {
        nodes.add(e.src.id)
        nodes.add(e.dst.id)
        edges.add(`${e.src.id}|${e.rel}|${e.dst.id}`)
      }
    }
    return { nodes, edges }
  }, [chain])

  return (
    <div className="app app-demo">
      <div className="demo-top">
        <header className="demo-header">
          <h1 className="demo-title">跨层溯源 Agent</h1>
          <p className="demo-sub">
            CiP-DMD 气缸底 · DMC-50H 铣床 · 98 个零件真实工艺信号 → 神经-符号归因（AI proposes, Logic disposes）
          </p>
          <button className="send-btn batch-btn" onClick={runBatch} disabled={batchBusy}>
            {batchBusy ? '分析中…' : '重新分析批次'}
          </button>
        </header>
        {Object.keys(rootSummary).length > 0 && (
          <div className="root-buttons">
            <span className="root-label">归因结果（推理后出现）：</span>
            {Object.entries(rootSummary).map(([k, n]) => (
              <button
                key={k}
                className={`root-btn${activeRoot === k ? ' is-active' : ''}`}
                onClick={() => void handlePickRoot(k)}
              >
                {k} <em>{n}</em>
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="demo-body">
        <ChatPane messages={messages} busy={batchBusy} status="" />
        <main className="content">
          <section className="panel ontology-panel">
            <h3 className="panel-title">本体知识图谱（点击节点看 ABox/TBox · 滚轮缩放 · 拖拽平移/节点）</h3>
            <OntologyGraph
              nodes={ontology.nodes}
              edges={ontology.edges}
              highlightNodes={highlight.nodes}
              highlightEdges={highlight.edges}
            />
          </section>
          <BatchTable rows={filteredRows} onSelectRow={handleSelectRow} selectedId={selectedSample?.part_id ?? null} />
          {chain && selectedSample ? (
            <ReactFlowProvider>
              <AttributionPanel chain={chain} sample={selectedSample} />
              <TraceGraph steps={chain.steps} status={chain.status} />
            </ReactFlowProvider>
          ) : null}
        </main>
      </div>
    </div>
  )
}

function summarize(rows: BatchRow[]): string {
  const pass = rows.filter((r) => r.status === 'PASS').length
  const mat = rows.filter((r) => r.locked === '来料尺寸不足').length
  const clamp = rows.filter((r) => r.locked === '工件夹持不平').length
  const fail = rows.filter((r) => r.status === 'FAILED').length
  return `正常 ${pass} / 来料尺寸不足 ${mat} / 工件夹持不平 ${clamp} / 无法归因 ${fail}`
}
