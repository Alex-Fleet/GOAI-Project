import { useCallback, useState } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import ChatPane from './components/ChatPane'
import TraceGraph from './components/TraceGraph'
import ActionPanel from './components/ActionPanel'
import type { TraceChain } from './types'

export default function App() {
  const [chain, setChain] = useState<TraceChain | null>(null)

  const handleChain = useCallback((c: TraceChain) => setChain(c), [])
  const handleStatus = useCallback((status: string) => {
    setChain((prev) => (prev ? { ...prev, status } : prev))
  }, [])

  return (
    <div className="app">
      <ChatPane onChain={handleChain} onStatus={handleStatus} />
      <main className="content">
        {chain ? (
          <ReactFlowProvider>
            <TraceGraph steps={chain.steps} status={chain.status} />
            <ActionPanel chain={chain} onUpdated={handleChain} />
          </ReactFlowProvider>
        ) : (
          <div className="empty">
            <p className="empty-title">分层溯源工作台</p>
            <p className="empty-hint">
              在左侧输入事故报告（对象 + 不合格指标），运行 7 步溯源链。
              推理路径逐层点亮于此处，处置建议在下方确认。
            </p>
          </div>
        )}
      </main>
    </div>
  )
}
