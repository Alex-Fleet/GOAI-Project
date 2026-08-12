"""一楼契约层：Agent 与平台、一楼与二楼的唯一边界（ARD §6）。

本模块只放通用数据结构与接口定义，禁止任何具体行业 / 设备 / 数据源字段。
修改红线（ARD §6.3）：只允许泛化，禁止业务特化——把契约读给另一行业工程师听，
如果他不需要理解任何具体工厂就能懂，则契约是通用的。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# 图引用
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeRef:
    """属性图节点引用（label = 节点表名，id = 主键，props = 读取的属性快照）。"""

    label: str
    id: str
    props: dict[str, Any] = field(default_factory=dict, compare=False)

    def __hash__(self) -> int:  # props 不参与比较/哈希（动态属性，快照性质）
        return hash((self.label, self.id))

    def __repr__(self) -> str:
        return f"<{self.label} {self.id}>"


@dataclass(frozen=True)
class EdgeRef:
    """图边轨迹（可回放）：src -(rel)-> dst。TraceStep.path 的元素。"""

    src: NodeRef
    rel: str
    dst: NodeRef


# ---------------------------------------------------------------------------
# 触发事实
# ---------------------------------------------------------------------------


@dataclass
class EvidenceEvent:
    """触发事实（适配器 → Agent）：出问题的对象 + 不合格指标。

    failed_indicators 是业务词，如 ["surface_roughness"]，类型本身通用（任意指标名）。
    raw_ref 指向原始证据（哈希链锚点，防篡改）。
    """

    entity_ref: str
    entity_type: str  # 对象类型，如 "part" | "batch" | "product"
    ts: float
    failed_indicators: list[str] = field(default_factory=list)
    raw_ref: str = ""


# ---------------------------------------------------------------------------
# 属性规则判定
# ---------------------------------------------------------------------------


@dataclass
class Verdict:
    """属性规则判定结果（决策三件套之「判定」）。

    observed / threshold 可为数值或字符串（枚举/包含比较）。
    operator 取值：>= | <= | > | < | == | != | contains | in
    """

    rule_id: str
    observed: Any
    threshold: Any
    operator: str
    passed: bool


# ---------------------------------------------------------------------------
# LLM 提议（假设，非结论）
# ---------------------------------------------------------------------------


@dataclass
class Proposal:
    """LLM 提议 = 假设，非结论。推理核把关验证后才成为 TraceStep。

    生命周期：LLM 产出 Proposal(pending) → 推理核沿图验证 + 属性判定
      → verified：由 Proposal 生成 TraceStep 进 TraceChain
      → rejected：换候选（每层候选上限 N，耗尽 → FAILED）
    """

    id: str
    layer: str  # "L1" | "L2" | "L3" | "L4"
    candidate: NodeRef
    hypothesis: str
    basis: list[EdgeRef] = field(default_factory=list)  # LLM 看图依据轨迹（防编理由）
    status: str = "pending"  # pending | verified | rejected
    verdict: Verdict | None = None  # 推理核把关结果（验证后填充）


# ---------------------------------------------------------------------------
# 单层结论 / 完整链
# ---------------------------------------------------------------------------


@dataclass
class TraceStep:
    """单层结论 = 路径 + 判定 + 依据（决策三件套，ARD §4.2）。"""

    layer: str  # "L1" | "L2" | "L3" | "L4" | "impact"
    path: list[EdgeRef] = field(default_factory=list)  # 沿图遍历的边轨迹（可回放）
    verdict: Verdict | None = None
    evidence_refs: list[str] = field(default_factory=list)  # 绑定的原始证据引用
    standard_clause: str | None = None  # 标准条款（可空）


@dataclass
class Action:
    """处置建议（READY 后交人确认 → 执行层落库）。"""

    id: str
    action_type: str  # "freeze" | "halt" | "claim" | "inspect" | ...
    target_ref: str
    description: str
    approved: bool = False
    result: str | None = None  # 执行层回填结果


@dataclass
class ExecutionReport:
    """人确认动作后，执行层的落库结果汇总。"""

    chain_id: str
    applied: list[Action]
    failed: list[Action]
    summary: str


@dataclass
class TraceChain:
    """一次事故完整推理链（服务层 → 交互层）。"""

    id: str
    trigger: EvidenceEvent
    steps: list[TraceStep] = field(default_factory=list)
    impact: dict[str, Any] = field(default_factory=dict)  # 波及面摘要
    actions: list[Action] = field(default_factory=list)  # 处置建议
    narrative: list[str] = field(default_factory=list)  # 每步人话解释（聊天窗流式）
    root_hash: str = ""
    status: str = "TRACING"  # TRACING / READY / CONFIRMED / EXECUTED / SEALED / FAILED
    note: str = ""  # FAILED 时标注缺失原因


# ---------------------------------------------------------------------------
# 平台接口（契约，实现不依赖彼此，只依赖本模块）
# ---------------------------------------------------------------------------


@runtime_checkable
class GraphStore(Protocol):
    """知识层：属性图查询。换图库实现不影响推理核。"""

    def query(self, start: NodeRef, rel: str, direction: str) -> list[EdgeRef]: ...
    def get_node(self, ref: NodeRef) -> NodeRef | None: ...
    def load_scope(self, scope: str) -> None: ...  # 按需加载（一楼可为空）


@runtime_checkable
class BusinessStore(Protocol):
    """业务层：台账 / 批次 / 工单 / 合同。Record 为通用 dict。"""

    def query(self, filters: dict[str, Any]) -> list[dict[str, Any]]: ...
    def apply(self, actions: list[Action]) -> list[ActionResult]: ...


@runtime_checkable
class Audit(Protocol):
    """审计底座：依据链 + 哈希链。append 返回该步哈希。"""

    def begin(self, trigger: EvidenceEvent) -> None: ...
    def append(self, step: TraceStep) -> str: ...
    def verify(self, root_hash: str) -> bool: ...
    def root(self) -> str: ...


@dataclass
class ActionResult:
    """单条动作的执行结果。"""

    action_id: str
    ok: bool
    message: str
