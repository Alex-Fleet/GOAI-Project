import { useState } from 'react'
import { confirmActions, getChain } from '../api'
import type { TraceChain } from '../types'

interface Props {
  chain: TraceChain
  onUpdated: (chain: TraceChain) => void
}

export default function ActionPanel({ chain, onUpdated }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function confirm() {
    setBusy(true)
    try {
      await confirmActions(chain.id, [...selected])
      const fresh = await getChain(chain.id)
      onUpdated(fresh)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="action-panel">
      <section className="action-col">
        <h3 className="section-title">波及面</h3>
        <ul className="impact-list">
          {Object.entries(chain.impact).map(([k, v]) => (
            <li key={k} className="impact-item">
              <span className="impact-key">{k}</span>
              <span className="impact-val">{String(v)}</span>
            </li>
          ))}
          {Object.keys(chain.impact).length === 0 && (
            <li className="impact-item muted">无波及记录</li>
          )}
        </ul>
      </section>
      <section className="action-col">
        <h3 className="section-title">处置建议</h3>
        {chain.actions.length === 0 ? (
          <p className="muted">无处置建议</p>
        ) : (
          <ul className="action-list">
            {chain.actions.map((a) => (
              <li key={a.id} className={`action-item${a.approved ? ' approved' : ''}`}>
                <label className="action-check">
                  <input
                    type="checkbox"
                    checked={selected.has(a.id) || a.approved}
                    disabled={chain.status !== 'READY' || a.approved}
                    onChange={() => toggle(a.id)}
                  />
                  <span className="action-type">{a.action_type}</span>
                </label>
                <p className="action-desc">{a.description}</p>
                {a.result && <p className="action-result">{a.result}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>
      <footer className="action-footer">
        <span className="hash" title="溯源根指纹（哈希链，可独立重算校验）">
          {chain.root_hash ? `#${chain.root_hash.slice(0, 12)}…` : '—'}
        </span>
        <button
          onClick={confirm}
          disabled={busy || chain.status !== 'READY' || selected.size === 0}
          className="confirm-btn"
        >
          {busy ? '执行中…' : chain.status === 'READY' ? `确认执行（${selected.size}）` : '已确认'}
        </button>
      </footer>
    </div>
  )
}
