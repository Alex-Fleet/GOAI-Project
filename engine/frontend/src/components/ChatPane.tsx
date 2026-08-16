import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { askChat } from '../api'

interface Msg {
  role: string
  text: string
}

interface Props {
  messages: Msg[]
  busy: boolean
  status: string
}

export default function ChatPane({ messages, busy, status }: Props) {
  const [input, setInput] = useState('')
  const [asking, setAsking] = useState(false)
  const [localMsgs, setLocalMsgs] = useState<Msg[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, localMsgs])

  async function send() {
    const q = input.trim()
    if (!q || asking) return
    setInput('')
    setLocalMsgs((m) => [...m, { role: 'user', text: q }])
    setAsking(true)
    try {
      const ans = await askChat(q)
      setLocalMsgs((m) => [...m, { role: 'agent', text: ans }])
    } catch (e) {
      setLocalMsgs((m) => [...m, { role: 'error', text: `问答失败：${String(e)}` }])
    }
    setAsking(false)
  }

  const all = [...messages, ...localMsgs]

  return (
    <aside className="chat-pane">
      <header className="chat-header">
        <span className="chat-title">溯源 Agent</span>
        <span className="chat-sub">
          神经-符号 · 白箱回放 · 哈希审计
          {status && <em className="chat-status"> · {status}</em>}
        </span>
      </header>
      <div className="chat-msgs">
        {all.length === 0 && (
          <p className="chat-placeholder">
            推理过程逐层流式输出；也可以直接提问 Agent（例：「空切一般是什么原因？」）。
          </p>
        )}
        {all.map((m, i) => (
          <div key={i} className={`msg msg-${m.role}`}>
            <ReactMarkdown>{m.text}</ReactMarkdown>
          </div>
        ))}
        {(busy || asking) && <div className="msg msg-agent">…</div>}
        <div ref={bottomRef} />
      </div>
      <div className="chat-input chat-qa">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void send()
          }}
          placeholder="提问 Agent（回车发送）"
          aria-label="问题"
        />
        <button onClick={() => void send()} disabled={asking || !input.trim()} className="send-btn">
          发送
        </button>
      </div>
    </aside>
  )
}
