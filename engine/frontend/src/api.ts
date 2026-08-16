import type { BatchRow } from './components/BatchTable'
import type { ExecutionReport, OntoData, SampleMeta, TraceChain } from './types'

// 后端地址：默认本机 8800，可用 VITE_API_BASE 覆盖（生产同源部署时留空走相对路径）。
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8800'

export async function startIncident(payload: Record<string, unknown>): Promise<TraceChain> {
  const res = await fetch(`${BASE}/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getSamples(): Promise<SampleMeta[]> {
  const res = await fetch(`${BASE}/samples`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getOntology(): Promise<OntoData> {
  const res = await fetch(`${BASE}/ontology`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function askChat(question: string): Promise<string> {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  const data = (await res.json()) as { answer?: string; error?: string }
  if (data.error) throw new Error(data.error)
  return data.answer ?? ''
}

export async function analyzeBatch(partIds?: string[], all = false): Promise<BatchRow[]> {
  const res = await fetch(`${BASE}/analyze_batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ part_ids: partIds, all }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getChain(id: string): Promise<TraceChain> {
  const res = await fetch(`${BASE}/chains/${id}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function confirmActions(
  chainId: string,
  actionIds: string[],
): Promise<ExecutionReport> {
  const res = await fetch(`${BASE}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chain_id: chainId, action_ids: actionIds }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

/**
 * SSE 流式拉取推理过程的人话解释（左栏聊天窗）。
 * 返回 abort 函数；组件卸载 / 重新提交时调用。
 */
export function streamNarrative(
  chainId: string,
  handlers: {
    onNarrative: (text: string) => void
    onDone: (status: string, rootHash: string) => void
  },
): () => void {
  const controller = new AbortController()
  void (async () => {
    const res = await fetch(`${BASE}/stream/${chainId}`, { signal: controller.signal })
    if (!res.ok || !res.body) return
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx: number
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const frame = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        const line = frame.split('\n').find((l) => l.startsWith('data: '))
        if (!line) continue
        try {
          const data = JSON.parse(line.slice(6)) as { type: string; text?: string; status?: string; root_hash?: string }
          if (data.type === 'narrative' && data.text) handlers.onNarrative(data.text)
          else if (data.type === 'done') handlers.onDone(data.status ?? '', data.root_hash ?? '')
        } catch {
          // 容忍损坏帧，不中断流
        }
      }
    }
  })().catch((err) => {
    if (err.name !== 'AbortError') console.error(err)
  })
  return () => controller.abort()
}
