import type { SampleMeta } from '../types'

interface Props {
  samples: SampleMeta[]
  selected: string | null
  onPick: (sample: SampleMeta) => void
}

const SYMPTOM_LABEL: Record<string, string> = {
  air_cut: '空切信号',
  overload: '过载信号',
  normal: '信号正常',
}

export default function AccidentPicker({ samples, selected, onPick }: Props) {
  return (
    <section className="accidents">
      <header className="accidents-head">
        <span className="accidents-title">真实事故样本（CiP-DMD 气缸底 · DMC-50H 铣床）</span>
        <span className="accidents-sub">点击事故卡，系统盲推溯源 + 归因</span>
      </header>
      <div className="accident-list">
        {samples.map((s) => (
          <button
            key={s.part_id}
            className={`accident-card${selected === s.part_id ? ' is-selected' : ''}`}
            onClick={() => onPick(s)}
          >
            <div className="accident-top">
              <span className="accident-name">{s.official_name}</span>
              <span className="accident-id">{s.part_id}</span>
            </div>
            <dl className="accident-facts">
              <div>
                <dt>表面粗糙度</dt>
                <dd>{s.surface_roughness.toFixed(2)}<em> / 上限 2.5</em></dd>
              </div>
              <div>
                <dt>工艺症状</dt>
                <dd>{SYMPTOM_LABEL[s.symptom] ?? s.symptom}</dd>
              </div>
              {s.signal && (
                <div>
                  <dt>端面电流均值</dt>
                  <dd>{s.signal.curr6_mean.toFixed(2)}<em> / 正常 1.49~3.39</em></dd>
                </div>
              )}
            </dl>
          </button>
        ))}
      </div>
    </section>
  )
}
