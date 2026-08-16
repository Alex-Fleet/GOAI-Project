// 与一楼契约（engine/contracts.py）对齐的响应类型——不落业务字段。

export interface NodeRef {
  label: string
  id: string
  props: Record<string, unknown>
}

export interface EdgeRef {
  src: NodeRef
  rel: string
  dst: NodeRef
}

export interface Verdict {
  rule_id: string
  observed: unknown
  threshold: unknown
  operator: string
  passed: boolean
}

export interface TraceStep {
  layer: string
  path: EdgeRef[]
  verdict: Verdict | null
  evidence_refs: string[]
  standard_clause: string | null
}

export interface Action {
  id: string
  action_type: string
  target_ref: string
  description: string
  approved: boolean
  result: string | null
}

export interface TraceChain {
  id: string
  trigger: EvidenceEvent
  steps: TraceStep[]
  impact: Record<string, unknown>
  actions: Action[]
  narrative: string[]
  root_hash: string
  status: string
  note: string
}

export interface EvidenceEvent {
  entity_ref: string
  entity_type: string
  ts: number
  failed_indicators: string[]
  raw_ref: string
}

export interface ExecutionReport {
  chain_id: string
  applied: Action[]
  failed: Action[]
  summary: string
}

// ---- demo 层：事故样本（ABox 个体，供前端事故选择）----

export interface SampleSignal {
  curr6_mean: number
  load6_mean: number
  curr6_peak: number
}

export interface SampleMeta {
  part_id: string
  official_anomaly: string
  official_name: string
  surface_roughness: number
  saw_weight: number | null
  signal: SampleSignal | null
  symptom: string
}

// ---- 本体图（d3-force 可视化）----

export interface OntoNode {
  id: string
  label: string
  name?: string
}

export interface OntoEdge {
  source: string
  target: string
  rel: string
}

export interface OntoData {
  nodes: OntoNode[]
  edges: OntoEdge[]
}
