import { useMemo } from 'react'

export interface BatchRow {
  part_id: string
  official_anomaly: string
  official_name: string
  surface_roughness: number | null
  symptom: string
  locked: string | null
  liability: string[]
  status: string
  chain_id?: string
}

interface Props {
  rows: BatchRow[]
  onSelectRow: (row: BatchRow) => void
  selectedId: string | null
}

const SYMPTOM_LABEL: Record<string, string> = {
  air_cut: '空切',
  overload: '过载',
  normal: '正常',
}

export default function BatchTable({ rows, onSelectRow, selectedId }: Props) {
  const summary = useMemo(() => {
    const pass = rows.filter((r) => r.status === 'PASS').length
    const materialShort = rows.filter((r) => r.locked === '来料尺寸不足').length
    const clamping = rows.filter((r) => r.locked === '工件夹持不平').length
    const unresolved = rows.filter((r) => r.status === 'FAILED').length
    return { pass, materialShort, clamping, unresolved }
  }, [rows])

  return (
    <div className="batch">
      <div className="batch-head">
        <span className="batch-title">批次归因（系统从数据中归因出几类问题）</span>
        <span className="batch-sub">共 {rows.length} 件 · 点击行展开单件推理链</span>
      </div>
      {rows.length > 0 && (
        <div className="batch-summary">
          <span className="sum-pass">正常 {summary.pass}</span>
          <span className="sum-mat">来料尺寸不足 {summary.materialShort}</span>
          <span className="sum-clamp">工件夹持不平 {summary.clamping}</span>
          <span className="sum-fail">无法归因 {summary.unresolved}</span>
        </div>
      )}
      <table className="batch-table">
        <thead>
          <tr>
            <th>零件</th>
            <th>表面粗糙度</th>
            <th>官方标注</th>
            <th>系统症状</th>
            <th>锁定根因</th>
            <th>责任方</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.part_id}
              className={`batch-row${selectedId === r.part_id ? ' is-selected' : ''}`}
              onClick={() => r.chain_id && onSelectRow(r)}
            >
              <td className="mono">{r.part_id}</td>
              <td className="mono">{r.surface_roughness != null ? r.surface_roughness.toFixed(2) : '—'}</td>
              <td>{OFFICIAL[r.official_anomaly] ?? r.official_anomaly}</td>
              <td>{SYMPTOM_LABEL[r.symptom] ?? r.symptom}</td>
              <td className={r.locked ? 'accent' : ''}>{r.locked ?? '—'}</td>
              <td className="mono">{r.liability.length ? r.liability.join(', ') : '—'}</td>
              <td>
                <span className={`badge badge-${r.status.toLowerCase()}`}>{r.status}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const OFFICIAL: Record<string, string> = {
  '0': '正常',
  '1': '来料短',
  '2': '夹持',
  '3': '杂项',
}
