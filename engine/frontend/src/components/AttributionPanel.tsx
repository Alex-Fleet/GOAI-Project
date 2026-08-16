import type { SampleMeta, TraceChain } from '../types'

interface Props {
  chain: TraceChain | null
  sample: SampleMeta | null
}

const SYMPTOM_NAMES: Record<string, string> = {
  air_cut: '端面铣削空切（电流极低）',
  overload: '端面铣削过载（电流偏高/尖峰）',
  normal: '工艺信号正常',
}

export default function AttributionPanel({ chain, sample }: Props) {
  if (!chain || !sample) {
    return (
      <section className="panel attribution">
        <h3 className="panel-title">归因结果</h3>
        <p className="panel-hint">选择一个事故样本，系统盲推溯源并归因根因。</p>
      </section>
    )
  }

  const attr = chain.steps.find((s) => s.layer === 'L2-attribution')
  const root = chain.steps.find((s) => s.layer === 'L4-root-cause')
  const symptom = attr?.verdict ? String(attr.verdict.observed) : ''
  const locked = attr?.verdict ? String(attr.verdict.threshold) : ''
  const passed = attr?.verdict?.passed ?? false
  const liabilities = (chain.impact?.liabilities as string[] | undefined) ?? []
  const penalty = chain.impact?.penalty as
    | { supplier: string; contract: string; rate: number; amount: number; value: number }
    | undefined

  const officialName = sample.official_name
  const systemName = passed ? (locked === 'material_short' ? '来料尺寸不足' : locked === 'clamping_error' ? '工件夹持不平' : locked) : '无法归因'
  const match = passed && ((officialName === '来料短' && locked === 'material_short') || (officialName === '夹持' && locked === 'clamping_error'))

  return (
    <section className="panel attribution">
      <h3 className="panel-title">归因结果</h3>
      <div className="attr-grid">
        <div className={`attr-chip symptom ${passed ? '' : 'warn'}`}>
          <span className="attr-label">检出症状</span>
          <span className="attr-value">{SYMPTOM_NAMES[symptom] ?? symptom}</span>
        </div>
        <div className="attr-chip root">
          <span className="attr-label">锁定根因</span>
          <span className="attr-value">{passed ? systemName : '无法归因（不硬出结论）'}</span>
        </div>
        <div className="attr-chip liable">
          <span className="attr-label">责任方</span>
          <span className="attr-value">
            {liabilities.length > 0 ? liabilities.join(', ') : '—'}
          </span>
        </div>
      </div>

      <div className={`blind-compare ${match ? 'is-match' : chain.status === 'FAILED' ? 'is-failed' : ''}`}>
        <div className="blind-title">盲推对照</div>
        <div className="blind-row">
          <span>官方标注</span>
          <strong>{officialName}</strong>
        </div>
        <div className="blind-row">
          <span>系统盲推</span>
          <strong>{chain.status === 'FAILED' ? '无法归因（诚实边界）' : systemName}</strong>
        </div>
        <div className="blind-verdict">
          {chain.status === 'FAILED'
            ? '系统如实拒绝下结论（杂项错误官方标注为「工艺数据不可见」）'
            : match
              ? '推理结果与官方标注一致 ✓'
              : '系统结论与官方标注存在差异，需人工复核'}
        </div>
      </div>

      {root && (
        <p className="panel-note">
          {root.verdict?.passed
            ? `责任沿根因锁定：${liabilities.join(', ')}（条款 ${String(root.verdict.threshold)} 覆盖）`
            : '根因责任未确认'}
        </p>
      )}

      {penalty && (
        <div className="penalty">
          <div className="penalty-title">追责 / 损失测算</div>
          <div className="penalty-row">
            <span>责任方</span>
            <strong>{penalty.supplier}</strong>
          </div>
          <div className="penalty-row">
            <span>合同 {penalty.contract}（违约金率 {penalty.rate}）</span>
            <span>订单 {penalty.amount.toLocaleString()} 元</span>
          </div>
          <div className="penalty-result">
            追偿 <strong>{penalty.value.toLocaleString()} 元</strong>
          </div>
        </div>
      )}
      {chain.root_hash && (
        <div className="hash-row">
          <span>溯源根哈希（哈希链可回放验证）</span>
          <code className="hash-val">{chain.root_hash}</code>
        </div>
      )}
    </section>
  )
}
