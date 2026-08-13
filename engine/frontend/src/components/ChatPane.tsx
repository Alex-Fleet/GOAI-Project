import { useEffect, useRef, useState } from 'react'
import { startIncident, streamNarrative } from '../api'
import type { TraceChain } from '../types'

interface Msg {
  role: 'user' | 'agent' | 'error'
  text: string
}

interface Props {
  onChain: (chain: TraceChain) => void
  onStatus: (status: string) => void
}

const SAMPLE = {
  entity_ref: 'P1',
  entity_type: 'product',
  ts: 100.0,
  failed_indicators: ['surface_roughness'],
  raw_ref: 'raw://P1/qcr',
}

export default function ChatPane({ onChain, onStatus }: Props) {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState(JSON.stringify(SAMPLE, null, 2))
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<() => void>(() => {})
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => () => abortRef.current(), []) // 卸载时中止 SSE

  async function send() {
    let payload: Record<string, unknown>
    try {
      payload = JSON.parse(input) as Record<string, unknown>
    } catch {
      setMessages((m) => [...m, { role: 'error', text: 'JSON 解析失败，请检查输入格式。' }])
      return
    }
    abortRef.current() // 中止上一轮流
    setBusy(true)
    const summary = `${payload.entity_ref} · ${String(payload.failed_indicators ?? []).replace(/"/g, '')}`
    setMessages((m) => [...m, { role: 'user', text: `事故：${summary}` }])
    try {
      const chain = await startIncident(payload)
      onChain(chain)
      abortRef.current = streamNarrative(chain.id, {
        onNarrative: (text) => setMessages((m) => [...m, { role: 'agent', text }]),
        onDone: (status, _hash) => {
          onStatus(status)
          setBusy(false)
        },
      })
    } catch (e) {
      setMessages((m) => [...m, { role: 'error', text: `启动失败：${String(e)}` }])
      setBusy(false)
    }
  }

  return (
    <aside className="chat-pane">
      <header className="chat-header">
        <span className="chat-title">溯源 Agent</span>
        <span className="chat-sub">分层下钻 · 白箱回放 · 哈希审计</span>
      </header>
      <div className="chat-msgs">
        {messages.length === 0 && (
          <p className="chat-placeholder">
            输入事故报告 JSON 后点击「开始溯源」。推理过程将在此逐层流式输出。
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg msg-${m.role}`}>
            {m.text}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <div className="chat-input">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          spellCheck={false}
          rows={5}
          aria-label="事故报告 JSON"
        />
        <button onClick={send} disabled={busy} className="send-btn">
          {busy ? '溯源中…' : '开始溯源'}
        </button>
      </div>
    </aside>
  )
}
